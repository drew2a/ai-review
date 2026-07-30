import argparse
import json
import os
import re
from pathlib import Path

import litellm
import yaml
from github import File, Github, GithubException
from jinja2 import Environment, FileSystemLoader

GITHUB_ACTIONS_BOT = 'github-actions[bot]'
HEADER = '# AI Review'
REVIEW_RESOLUTIONS = ('APPROVE', 'REQUEST_CHANGES', 'COMMENT')

# Schema enforced on the LLM response, so the output needs no marker-based parsing.
RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {
        'summary': {
            'type': 'string',
            'description': 'Human-readable review summary in Markdown, posted as a PR comment.',
        },
        'comments': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'file': {'type': 'string'},
                    'line': {'type': 'integer'},
                    'message': {'type': 'string'},
                },
                'required': ['file', 'line', 'message'],
                'additionalProperties': False,
            },
        },
        'review': {
            'type': 'object',
            'properties': {
                'resolution': {'type': 'string', 'enum': list(REVIEW_RESOLUTIONS)},
                'review_message': {'type': 'string'},
            },
            'required': ['resolution', 'review_message'],
            'additionalProperties': False,
        },
    },
    'required': ['summary', 'comments', 'review'],
    'additionalProperties': False,
}

HUNK_HEADER_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')

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


class BlockStyleDumper(yaml.SafeDumper):
    """ Dumper that writes multi-line strings as literal blocks, which keeps diffs readable."""


def represent_str(dumper: yaml.SafeDumper, data: str):
    style = '|' if '\n' in data else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style=style)


BlockStyleDumper.add_representer(str, represent_str)


def dump_to_yaml(data: dict | list[dict] | None) -> str:
    """ Dump a dictionary or list of dictionaries to YAML with markdown code block."""
    if not data:
        return ''

    yaml_dump = yaml.dump(data, Dumper=BlockStyleDumper, allow_unicode=True, sort_keys=False)

    return f'```yaml\n{yaml_dump}```'


def is_previous_ai_review(comment) -> bool:
    """ Check whether a comment is a review previously posted by this action."""
    user = comment.user
    return bool(comment.body) and HEADER in comment.body and bool(user) and user.login == GITHUB_ACTIONS_BOT


def collect_pr_comments(pr) -> list[dict]:
    """
    Collect the comments of the PR conversation.

    Reviews previously posted by this action are skipped, so the LLM is not fed its own output.
    """
    return [
        {
            'author': comment.user.login if comment.user else '',
            'created_at': str(comment.created_at),
            'body': comment.body,
        }
        for comment in pr.get_issue_comments()
        if not is_previous_ai_review(comment)
    ]


def describe_comment_location(comment) -> dict:
    """
    Describe which lines of which file a review comment points to.

    `line` is the last line of the commented range and `start_line` the first one, both in the new
    version of the file unless `side` is LEFT.
    """
    location = {'file': comment.path}
    if comment.start_line and comment.start_line != comment.line:
        location['lines'] = f'{comment.start_line}-{comment.line}'
    else:
        location['line'] = comment.line
    location['side'] = comment.side or 'RIGHT'

    return location


def collect_review_comments(pr) -> list[dict]:
    """
    Collect the review comments left on the code, grouped into threads.

    Replies are chained under the comment that started the thread, so the discussion of a single
    place in the code stays together. Each thread also carries the `diff_hunk` it was written
    against, because a comment is only meaningful together with the code it points to.

    Threads on code that is no longer part of the diff (GitHub clears their `line`) are dropped:
    their line numbers refer to an older version of the file, so they would only mislead the LLM
    about the current state of the code.
    """
    threads: dict[int, dict] = {}
    root_ids: dict[int, int] = {}
    outdated_roots: set[int] = set()

    for comment in pr.get_review_comments():
        parent_id = comment.in_reply_to_id
        # Comments arrive oldest first, so a parent is always resolved before its replies.
        root_id = root_ids.get(parent_id, parent_id) if parent_id else comment.id
        root_ids[comment.id] = root_id

        if root_id in outdated_roots:
            continue

        thread = threads.get(root_id)
        if thread is None:
            if comment.line is None:
                outdated_roots.add(root_id)
                continue
            thread = threads[root_id] = {
                **describe_comment_location(comment),
                'url': comment.html_url,
                'diff_hunk': comment.diff_hunk,
                'comments': [],
            }

        thread['comments'].append({
            'author': comment.user.login if comment.user else '',
            'created_at': str(comment.created_at),
            'body': comment.body,
        })

    return list(threads.values())


def process_review(title: str, body: str | None, diff_string, pr_author: str, args, debug,
                   pr_comments: list[dict] | None = None,
                   review_comments: list[dict] | None = None):
    """ Calls the LLM API to generate a review based on the PR title, body, diff and comments."""

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
        'DIFF': diff_string,
        'PR_COMMENTS': dump_to_yaml(pr_comments),
        'REVIEW_COMMENTS': dump_to_yaml(review_comments),
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
        messages=messages,
        response_format={
            'type': 'json_schema',
            'json_schema': {'name': 'code_review', 'strict': True, 'schema': RESPONSE_SCHEMA},
        },
    )

    return response.choices[0].message.content


def collect_commentable_lines(diff_files) -> dict[str, set[int]]:
    """
    Map each file of the diff to the line numbers a review comment can be attached to.

    Those are the lines of the new version of the file that appear in the diff: added lines and
    unchanged context lines. GitHub rejects a review whose comment points anywhere else.
    """
    commentable: dict[str, set[int]] = {}

    for diff_file in diff_files:
        lines = commentable.setdefault(diff_file.filename, set())
        if not diff_file.patch:
            continue
        current_line_number = None
        for line in diff_file.patch.splitlines():
            match = HUNK_HEADER_RE.match(line)
            if match:
                current_line_number = int(match.group(1))
            elif line.startswith((' ', '+')) and current_line_number is not None:
                lines.add(current_line_number)
                current_line_number += 1

    return commentable


def build_inline_comments(comments: list[dict], commentable_lines: dict[str, set[int]]) -> list[dict]:
    """
    Convert the comments of the LLM output into GitHub review comments.

    A comment that does not point at a commentable line of the diff is dropped, because a single
    misplaced comment would make GitHub reject the whole review.
    """
    inline_comments = []
    for comment in comments:
        filename = comment.get('file')
        message = comment.get('message')
        try:
            line = int(comment.get('line'))
        except (TypeError, ValueError):
            line = None

        if not filename or not message or line not in commentable_lines.get(filename, set()):
            print(f'Skipping comment that does not point at the diff: {comment}')
            continue

        inline_comments.append({'path': filename, 'line': line, 'side': 'RIGHT', 'body': message})

    return inline_comments


def publish_review(review_content, github_token, debug, llm_model, add_review_resolution):
    """
    Parses the LLM response, which RESPONSE_SCHEMA constrains to a single JSON object:
    {
      "summary": "<markdown review summary>",
      "comments": [ {"file": "<path>", "line": <line>, "message": "<markdown>"}, ... ],
      "review": {
          "resolution": "<APPROVE|REQUEST_CHANGES|COMMENT>",
          "review_message": "<review text>"
      }
    }

    The function then:
      - Replaces the previous summary comment of this action with one holding the new summary.
      - Submits a single PR review whose inline comments are the "comments" entries. The review
        keeps the neutral COMMENT event unless add_review_resolution is on and the "review" block
        carries a valid resolution. Inline comments of previous runs are left in place on purpose:
        they are collected as context on the next run, which is what keeps the review from
        repeating itself.
    """
    if debug:
        print(review_content)

    tech_info = None
    json_str = extract_json(review_content)
    if json_str:
        try:
            tech_info = json.loads(json_str)
        except json.JSONDecodeError as e:
            print("Error parsing the review JSON:", e)

    if tech_info is None:
        # The model ignored the enforced schema; its raw output is still a review worth posting.
        tech_info = {}
        human_summary = (review_content or '').strip()
    else:
        human_summary = (tech_info.get('summary') or '').strip()

    g = Github(github_token)
    repo = g.get_repo(github_repo)
    pr_number = int(github_ref.split('/')[-2])
    pr = repo.get_pull(pr_number)

    # Delete previous summary comments from GitHub Actions that include the HEADER
    for comment in pr.get_issue_comments():
        if is_previous_ai_review(comment):
            comment.delete()

    if human_summary:
        comment = f"{HEADER} \n\n{human_summary}"
        if debug:
            comment += f"\n\n*Model version: {llm_model}*"

        pr.create_issue_comment(comment)

    comments = tech_info.get('comments') or tech_info.get('annotations') or []
    inline_comments = build_inline_comments(comments, collect_commentable_lines(pr.get_files()))

    review_data = tech_info.get('review') or {}
    resolution = review_data.get('resolution')
    review_message = review_data.get('review_message', '')

    event = 'COMMENT'
    body = ''
    if add_review_resolution:
        if resolution in REVIEW_RESOLUTIONS:
            event = resolution
            body = review_message
        else:
            print(f"Unknown resolution '{resolution}' in review JSON. Falling back to COMMENT.")

    # An empty APPROVE review is still submitted: unlike the other events, GitHub accepts it
    # without a body, and dropping it would lose the resolution.
    if inline_comments or body or event == 'APPROVE':
        try:
            pr.create_review(body=body, event=event, comments=inline_comments)
        except GithubException as e:
            print("Error submitting the PR review:", e)


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

    for line in lines:
        match = HUNK_HEADER_RE.match(line)
        if match:
            current_line_number = int(match.group(1))
            output_lines.append(line)
        else:
            if line.startswith((" ", "+")):
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
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else None


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

    pr_comments = collect_pr_comments(pr)
    review_comments = collect_review_comments(pr)

    add_review_resolution = args.add_review_resolution.lower() == 'true'
    review_content = process_review(pr.title, pr.body, diff_string, pr_author, args, debug,
                                    pr_comments=pr_comments, review_comments=review_comments)

    llm_model = os.environ.get('LLM_MODEL')
    publish_review(review_content, args.github_token, debug, llm_model, add_review_resolution)
