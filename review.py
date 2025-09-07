import argparse
import json
import os
import re
from pathlib import Path
from typing import Optional

import requests
import yaml
from github import File, Github
from jinja2 import Environment, FileSystemLoader

GITHUB_ACTIONS_BOT = 'github-actions[bot]'
HEADER = '# AI Review'

# Environment variables set by GitHub Actions
github_ref = os.environ.get('GITHUB_REF')
github_repo = os.environ.get('GITHUB_REPOSITORY')

supported_models = {
    '^gpt-4': {
        'header': lambda key, version: {
            'Authorization': f"Bearer {key}",  # for OpenAPI
            "api-key": key,  # for Azure
            'Api-Version': version,
            'Content-Type': 'application/json'
        },
        'parse_json': lambda d: d['choices'][0]['message']['content'],
        'prompt': lambda model, system_message, user_message: {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]
        },
    },
    '^o1': {
        'header': lambda key, version: {
            'Authorization': f"Bearer {key}",  # for OpenAPI
            "api-key": key,  # for Azure
            'Api-Version': version,
            'Content-Type': 'application/json'
        },
        'parse_json': lambda d: d['choices'][0]['message']['content'],
        'prompt': lambda model, system_message, user_message: {
            "model": model,
            "messages": [
                {"role": "user", "content": system_message},
                {"role": "user", "content": user_message}
            ]
        },
    },
    '^claude-3': {
        'header': lambda key, version: {
            "x-api-key": key,
            'anthropic-version': version,
            'Content-Type': 'application/json'
        },
        'parse_json': lambda d: d['content'][0]['text'],
        'prompt': lambda model, system_message, user_message: {
            "model": model,
            "system": system_message,
            'max_tokens': 1024,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        },
    },
    '^gemini-2': {
        'header': lambda key, version: {
            'x-goog-api-key': key,
            'Content-Type': 'application/json'
        },
        'parse_json': lambda d: (
            d['candidates'][0]['content']['parts'][0]['text']
        ),
        'prompt': lambda model, system_message, user_message: {
            "system_instruction": {
                "parts": [{"text": system_message}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_message}]
                }
            ]
        },
    }
}


def parse_args():
    parser = argparse.ArgumentParser(description='AI Code Review Action')
    parser.add_argument('api_endpoint', type=str, help='LLM API endpoint')
    parser.add_argument('api_key', type=str, help='LLM API key')
    parser.add_argument('api_version', type=str, help='API version')
    parser.add_argument('llm_model', type=str, help='LLM model name')
    parser.add_argument('github_token', type=str, help='GitHub Token')
    parser.add_argument('debug', type=str, help='Debug mode')
    parser.add_argument('add_review_resolution', type=str, help='Add review resolution')
    parser.add_argument('add_joke', type=str, help='Add joke')

    return parser.parse_args()


def get_model(pattern):
    """ Return the model name that matches the pattern. """
    if m := next((m for m in supported_models if re.match(m, pattern)), None):
        return m
    raise ValueError(f'Unsupported model pattern: {pattern}. Supported patterns are: {list(supported_models.keys())}')


def dump_to_yaml(data: dict | list[dict] | None) -> str:
    """ Dump a dictionary or list of dictionaries to YAML with markdown code block."""
    if not data:
        return ''

    yaml_dump = yaml.dump(data, allow_unicode=True, sort_keys=False)

    return f'```yaml\n{yaml_dump}```'


def process_review(title: str, body: Optional[str], diff_string, args, debug):
    """ Calls the LLM API to generate a review based on the PR title, body, and diff."""

    system_prompt = Path('/app/prompts/system_prompt.txt').read_text()
    if args.add_joke.lower() == 'true':
        humor_integration = Path('/app/prompts/humor_integration.txt').read_text()
        system_prompt = f'{system_prompt}\n{humor_integration}'

    env = Environment(
        loader=FileSystemLoader('/app/prompts'),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True
    )

    user_context = {
        'INPUT': dump_to_yaml({
            'pr_title': title,
            'pr_body': body,
        }),
        'DIFF': diff_string
    }

    user_template = env.get_template('user_prompt.txt')
    user_prompt = user_template.render(**user_context)

    if debug:
        print(user_prompt)

    model = get_model(args.llm_model)
    prompt = supported_models[model]['prompt'](args.llm_model, system_prompt, user_prompt)

    response = requests.post(
        args.api_endpoint,
        headers=supported_models[model]['header'](args.api_key, args.api_version),
        json=prompt
    )
    response.raise_for_status()
    return supported_models[model]['parse_json'](response.json())


def publish_annotations(summary_content, github_token, debug, llm_model, add_review_resolution):
    """
    Splits the LLM response into two parts:
      1. The human-readable summary (before the marker).
      2. The technical information after the marker ### TECHNICAL INFORMATION.

    The technical information must be a JSON block with the following structure:
    {
      "annotations": [ ... ],
      "review": {
          "resolution": "<APPROVE|REQUEST_CHANGES|COMMENT>",
          "review_message": "<review text>"
      }
    }

    The function then:
      - Prints annotations in the format ::warning file={filename},line={line}::{message}
      - Posts an issue comment with the summary in the PR.
      - If a review block is present, submits a PR review via the GitHub API.
    """
    if debug:
        print(summary_content)

    marker = "### TECHNICAL INFORMATION"
    if marker in summary_content:
        parts = summary_content.split(marker, 1)
        human_summary = parts[0].strip()
        technical_info_str = parts[1].strip()
    else:
        human_summary = summary_content
        technical_info_str = None

    # Process the JSON block with technical information (annotations)
    technical_info_str = extract_json(technical_info_str)
    if technical_info_str:
        try:
            tech_info = json.loads(technical_info_str)
            annotations = tech_info.get("annotations", [])
            for annotation in annotations:
                filename = annotation.get("file")
                line = annotation.get("line")
                message = annotation.get("message")
                output_line = f"::warning file={filename},line={line}::{message}"
                print(output_line)
        except json.JSONDecodeError as e:
            print("Error parsing technical information JSON (annotations):", e)

    # Post a PR comment with the human-readable summary
    g = Github(github_token)
    repo = g.get_repo(github_repo)
    pr_number = int(github_ref.split('/')[-2])
    pr = repo.get_pull(pr_number)

    # Delete previous comments from GitHub Actions that include the HEADER
    for comment in pr.get_issue_comments():
        print(comment.user.login)
        if HEADER in comment.body and comment.user.login == GITHUB_ACTIONS_BOT:
            comment.delete()

    if human_summary:
        comment = f"{HEADER} \n\n{human_summary}"
        if debug:
            comment += f"\n\n*Model version: {llm_model}*"

        pr.create_issue_comment(comment)

    # If a review block is present, submit a PR review via the GitHub API
    if technical_info_str and add_review_resolution:
        try:
            tech_info = json.loads(technical_info_str)
            review_data = tech_info.get("review")
            if review_data:
                resolution = review_data.get("resolution")
                review_message = review_data.get("review_message", "")
                # Validate the resolution value
                if resolution not in ["APPROVE", "REQUEST_CHANGES", "COMMENT"]:
                    print(f"Unknown resolution '{resolution}' in review JSON. Skipping PR review.")
                else:
                    pr.create_review(body=review_message, event=resolution)
        except json.JSONDecodeError as e:
            print("Error parsing technical information JSON (review):", e)


def help_llm(diff_file: File):
    """
    Creates a string for the LLM that contains:
      - The filename and raw URL.
      - The diff with line numbers (corresponding to the new file version).
    """
    lines = diff_file.patch.splitlines()
    output_lines = [
        f'\nFilename: {diff_file.filename}',
        'Patch:',
        "```"
    ]
    current_line_number = None
    hunk_header_re = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')

    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line_number = int(match.group(1))
            output_lines.append(line)
        else:
            if line.startswith(" ") or line.startswith("+"):
                if current_line_number is not None:
                    annotated_line = f"{current_line_number:4d}: {line}"
                    current_line_number += 1
                else:
                    annotated_line = "   ? : " + line
                output_lines.append(annotated_line)
            elif line.startswith("-"):
                output_lines.append("      " + line)
            else:
                output_lines.append(line)
    output_lines.append("```")
    return "\n".join(output_lines)


def extract_json(text):
    if not text:
        return text
    return re.search(r'\{.*\}', text, re.S).group(0)


if __name__ == "__main__":
    args = parse_args()

    g = Github(args.github_token)
    repo = g.get_repo(github_repo)
    pr_number = github_ref.split('/')[-2]
    pr = repo.get_pull(int(pr_number))

    diff = pr.get_files()

    diff_string = "\n".join(
        help_llm(f) for f in diff if f.patch
    )
    debug = args.debug.lower() == 'true'

    add_review_resolution = args.add_review_resolution.lower() == 'true'
    review_content = process_review(pr.title, pr.body, diff_string, args, debug)

    publish_annotations(review_content, args.github_token, debug, args.llm_model, add_review_resolution)
