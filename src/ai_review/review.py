import argparse
import json
import os
import re
from pathlib import Path
from typing import Optional

import litellm
import yaml
from github import File, Github
from jinja2 import Environment, FileSystemLoader

GITHUB_ACTIONS_BOT = 'github-actions[bot]'
HEADER = '# AI Review'

# Environment variables set by GitHub Actions
github_ref = os.environ.get('GITHUB_REF')
github_repo = os.environ.get('GITHUB_REPOSITORY')


def parse_args():
    parser = argparse.ArgumentParser(description='AI Code Review Action')
    parser.add_argument('github_token', type=str, help='GitHub Token')
    parser.add_argument('debug', type=str, help='Debug mode')
    parser.add_argument('add_review_resolution', type=str, help='Add review resolution')
    parser.add_argument('add_joke', type=str, help='Add joke')
    parser.add_argument('author_customization', type=str, help='Author customization YAML')

    return parser.parse_args()


def dump_to_yaml(data: dict | list[dict] | None) -> str:
    """ Dump a dictionary or list of dictionaries to YAML with markdown code block."""
    if not data:
        return ''

    yaml_dump = yaml.dump(data, allow_unicode=True, sort_keys=False)

    return f'```yaml\n{yaml_dump}```'


def process_review(title: str, body: Optional[str], diff_string, pr_author: str, args, debug):
    """ Calls the LLM API to generate a review based on the PR title, body, and diff."""

    system_prompt = Path('/app/prompts/system_prompt.txt').read_text()
    if args.add_joke.lower() == 'true':
        humor_integration = Path('/app/prompts/humor_integration.txt').read_text()
        system_prompt = f'{system_prompt}\n{humor_integration}'

    # Apply author-specific customizations
    customizations = parse_author_customization(args.author_customization)
    author_prompt_addition = get_author_specific_prompt_additions(pr_author, customizations)
    if author_prompt_addition:
        system_prompt += f"\n## Author Customization\n{author_prompt_addition}"

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
            'pr_author': pr_author,
        }),
        'DIFF': diff_string
    }

    user_template = env.get_template('user_prompt.txt')
    user_prompt = user_template.render(**user_context)

    if debug:
        print(system_prompt)
        print(user_prompt)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    llm_model = os.environ.get('LLM_MODEL')

    # litellm handles api_key, base_url, api_version from env vars automatically
    response = litellm.completion(
        model=llm_model,
        messages=messages
    )

    return response.choices[0].message.content


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


def parse_author_customization(customization_yaml: str):
    """Parse the author customization YAML and return a dictionary."""
    if not customization_yaml:
        return {}
    
    try:
        return yaml.safe_load(customization_yaml) or {}
    except yaml.YAMLError as e:
        print(f"Warning: Failed to parse author customization YAML: {e}")
        return {}


def get_author_specific_prompt_additions(pr_author: str, customizations: dict):
    """Get author-specific prompt additions based on customization rules."""
    value = customizations.get(pr_author, '')
    return str(value)


if __name__ == "__main__":
    args = parse_args()

    g = Github(args.github_token)
    repo = g.get_repo(github_repo)
    pr_number = github_ref.split('/')[-2]
    pr = repo.get_pull(int(pr_number))

    # Get PR author information
    pr_author = pr.user.login if pr.user else ""

    diff = pr.get_files()

    diff_string = "\n".join(
        help_llm(f) for f in diff if f.patch
    )
    debug = args.debug.lower() == 'true'

    add_review_resolution = args.add_review_resolution.lower() == 'true'
    review_content = process_review(pr.title, pr.body, diff_string, pr_author, args, debug)

    llm_model = os.environ.get('LLM_MODEL')
    publish_annotations(review_content, args.github_token, debug, llm_model, add_review_resolution)
