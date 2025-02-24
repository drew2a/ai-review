import argparse
import json
import os
import re

import requests
from github import File, Github

HEADER = '## AI Review'
GITHUB_ACTIONS_BOT = 'github-actions[bot]'

# Environment variables set by GitHub Actions
github_ref = os.environ['GITHUB_REF']
github_repo = os.environ['GITHUB_REPOSITORY']


def parse_args():
    parser = argparse.ArgumentParser(description='AI Code Review Action')
    parser.add_argument('api_endpoint', type=str, help='LLM API endpoint')
    parser.add_argument('api_key', type=str, help='LLM API key')
    parser.add_argument('api_version', type=str, help='API version')
    parser.add_argument('llm_model', type=str, help='LLM model name')
    parser.add_argument('github_token', type=str, help='GitHub Token')
    parser.add_argument('debug', type=str, help='Debug mode')
    parser.add_argument('add_review_resolution', type=str, help='Add review resolution')
    return parser.parse_args()


def get_pr_diff(github_token):
    """
    Retrieve the pull request diff files using the GitHub API.
    """
    g = Github(github_token)
    repo = g.get_repo(github_repo)
    pr_number = github_ref.split('/')[-2]
    pr = repo.get_pull(int(pr_number))
    return pr.get_files()


def process_review(diff_content, args):
    """
    Read system and user prompts, replace the diff placeholder with diff content,
    call the LLM API, and return the response content.
    """
    with open('/app/prompts/system_prompt.txt') as f:
        system_prompt = f.read()

    with open('/app/prompts/user_prompt.txt') as f:
        user_prompt = f.read().replace('{{DIFF_CONTENT}}', diff_content)

    system_role = 'system' if args.llm_model.startswith("gpt-4") else 'user'
    response = requests.post(
        args.api_endpoint,
        headers={
            'Authorization': f"Bearer {args.api_key}",  # for OpenAPI
            "api-key": args.api_key,  # for Azure
            'Api-Version': args.api_version,
            'Content-Type': 'application/json'
        },
        json={
            "model": args.llm_model,
            "messages": [
                {"role": system_role, "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
    )
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


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


if __name__ == "__main__":
    args = parse_args()

    diff = get_pr_diff(args.github_token)
    diff_content = "\n".join(
        help_llm(f) for f in diff if f.patch
    )
    debug = args.debug.lower() == 'true'
    add_review_resolution = args.add_review_resolution.lower() == 'true'

    if debug:
        print(diff_content)

    review_content = process_review(diff_content, args)
    publish_annotations(review_content, args.github_token, debug, args.llm_model, add_review_resolution)
