[![Pytest](https://github.com/drew2a/ai-review/actions/workflows/pytest.yml/badge.svg)](https://github.com/drew2a/ai-review/actions/workflows/pytest.yml)
[![Release](https://img.shields.io/github/v/release/drew2a/ai-review?logo=github)](https://github.com/drew2a/ai-review/releases/latest)
[![Marketplace](https://img.shields.io/badge/Marketplace-Liberty%20AI%20PR%20Review-2088FF?logo=github)](https://github.com/marketplace/actions/liberty-ai-pr-review)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)

# AI Code Review Action

A GitHub Action that provides automated code review using AI to analyze pull request changes.

## Features

- Automatically reviews pull request changes using AI
- Provides detailed code suggestions and improvements
- Posts real review comments attached to the changed lines, plus a summary comment on the PR
- Remembers its own previous comments, so re-running the review does not repeat them
- Takes the existing PR discussion into account (see [Discussion Context](#discussion-context))
- Works with any programming language
- Supports different AI models and API endpoints
- Optional review resolution statuses (e.g., "APPROVE", "REQUEST_CHANGES", "COMMENT")
- Debug mode for enhanced logging

## Supported models

This action uses [LiteLLM](https://docs.litellm.ai/docs/providers), so it supports **100+ LLMs** including:

- **OpenAI** (GPT-5.4, GPT-4o, o1, etc.)
- **Anthropic** (Claude 3.5 Sonnet, Claude 3.7 Sonnet, etc.)
- **Google VertexAI / Gemini** (Gemini 1.5 Pro, Gemini 2.0 Flash, etc.)
- **Azure OpenAI**
- **HuggingFace**
- **Ollama**
- ... and many more.

See the [LiteLLM Providers documentation](https://docs.litellm.ai/docs/providers) for the full list of supported models and the required environment variables for each provider.

### My (Subjective) Review of the Particular Models

I’ll grade them on a scale from **0 to 10**, where:

- **0** → Completely irrelevant comments
- **3** → My fresh junior/mid-level colleague
- **5** → My mid-level colleague who reads Stack Overflow
- **8** → Me
- **10** → My very smart colleague

So, based on this **(highly unscientific) scale**:

- **gpt-4o** → **2**
- **o1** → **3**
- **claude-3-5-sonnet** → **5**
- **claude-3-7-sonnet** → **6**
- **gemini-2.0-flash** → **2**
- **gemini-2.5-pro** → **3**
- **gpt-5.6-terra** → **7**

## Inputs

| Name                    | Description                                               | Required | Default              |
|-------------------------|-----------------------------------------------------------|----------|----------------------|
| `github_token`          | GitHub token for authentication                           | true     | -                    |
| `debug`                 | Enable debug mode (true/false)                            | false    | `false`              |
| `add_review_resolution` | Add review resolution (APPROVE, REQUEST_CHANGES, COMMENT) | false    | `false`              |
| `add_joke`              | Add a joke to the review comment                          | false    | `true`               |
| `author_customization`  | YAML configuration for customizing reviews based on PR author | false | -                    |

## Environment Variables

The action relies on environment variables for LLM configuration, handled by [litellm](https://docs.litellm.ai/docs/).

| Name | Description | Required |
|------|-------------|----------|
| `LLM_MODEL` | The model name to use (e.g. `gpt-5.4`, `claude-3-5-sonnet`, `gemini/gemini-1.5-pro`) | Yes |
| `OPENAI_API_KEY` | API Key for OpenAI (if using OpenAI models) | Conditional |
| `ANTHROPIC_API_KEY` | API Key for Anthropic (if using Claude models) | Conditional |
| `GEMINI_API_KEY` | API Key for Google Gemini (if using Gemini models) | Conditional |
| `OPENAI_API_BASE` | Custom API endpoint (if needed) | Optional |

*Note: Check the [LiteLLM documentation](https://docs.litellm.ai/docs/providers) for the specific environment variables required for your chosen provider.*

## Usage

To use this action in your GitHub workflow, add the following step:

```yaml
- uses: drew2a/ai-review@v1
  env:
    LLM_MODEL: gpt-4o
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    debug: false
    add_review_resolution: false
    add_joke: true
    author_customization: |
      torvalds: "This is an experienced developer. Focus on architecture and design patterns."
      defunkt: "This is a junior developer. Provide educational feedback and explanations."
```

### Example Workflow

```yaml
name: AI Code Review

on: [ pull_request_target ]

permissions:
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: drew2a/ai-review@v1
        env:
          LLM_MODEL: ${{ secrets.LLM_MODEL }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          # Add other env vars required by litellm for your specific provider
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          debug: true
          add_review_resolution: false
          add_joke: true
```

### Why `pull_request_target`

`pull_request` looks like the natural trigger, but GitHub strips two things from those runs when
the PR comes from Dependabot or from a fork:

- the repository secrets, so `secrets.OPENAI_API_KEY` and friends arrive empty;
- write access, so `GITHUB_TOKEN` is read-only and the review cannot be posted. The
  `permissions:` block does not lift this.

`pull_request_target` runs the workflow in the context of the base branch, which keeps both the
secrets and a writable token, so Dependabot and fork PRs are reviewed like any other. The usual
warning about this trigger is that it hands a privileged token to a workflow running on untrusted
code — that does not apply here, because `actions/checkout` checks out the *base* commit and the
action never executes anything from the pull request. It reads the title, description, diff and
comments through the GitHub API, and the model it sends them to has no tools. The remaining
exposure is that the content of a PR can influence the wording of its own review.

If you would rather stay on `pull_request`, the alternative is to keep the review off Dependabot
PRs (`if: github.actor != 'dependabot[bot]'`) or to duplicate the LLM key into the separate
Dependabot secret store and pass a PAT as `github_token`.

## Discussion Context

Besides the title, description and diff, the review is given the discussion that already happened on
the PR, so it can build on it instead of repeating it. Two things are collected:

1. **PR conversation comments** — the comments on the PR itself. Summaries previously posted by
   this action are skipped, because they are replaced by the new summary anyway.
2. **Review comments on the code** — the comments attached to specific lines. Replies are chained
   into threads, so the whole discussion about one place in the code stays together. Comments the
   action itself left on previous runs are included on purpose: the model is told they are its own,
   which keeps it from repeating them.

Each thread is passed with the location it points to, the code it was written against and a link:

```yaml
- file: src/app.py
  lines: 8-10
  side: RIGHT
  url: https://github.com/owner/repo/pull/1#discussion_r1
  diff_hunk: |-
    @@ -5,3 +5,4 @@
    -old
    +new
  comments:
  - author: alice
    created_at: 2026-01-01 10:00:00+00:00
    body: This can overflow for large inputs.
  - author: bob
    created_at: 2026-01-01 11:00:00+00:00
    body: Good catch, fixed in the last commit.
```

`side` tells whether the lines refer to the new (`RIGHT`) or the old (`LEFT`) version of the file. A
thread whose code has fallen out of the diff (for example because the author pushed a fix) is
considered outdated and is left out of the context, since its line numbers would refer to an older
version of the file.

This needs no configuration, but note that the action reads the comments through the same
`github_token`, so the token needs read access to the pull request (the `pull-requests: write`
permission in the example workflow already covers it).

## Author Customization

The `author_customization` parameter allows you to customize the review behavior based on the PR author's GitHub username. This is useful for providing different types of feedback for team members with different experience levels or roles.

The customization is appended to the prompt on top of the default behaviour rather than replacing
it. In particular, a customization that sets a persona or a tone does not switch the humor of
`add_joke` off: the joke is then delivered in that persona's voice.

### Configuration Format

The customization is provided as YAML using actual GitHub usernames:

```yaml
torvalds: "Custom review guidance for this user"
defunkt: "Different guidance for another user"
```

### Example Configuration

Here's an example for a team with users who get customized behavior:

```yaml
author_customization: |
  torvalds: "Use a more friendly manner since they're beginners. Give more examples and explanations to help them learn."
  defunkt: "Use a super formal tone and provide low-level grounding. Focus on technical precision and detailed analysis."
```

### Role-Based Example

You can also organize by roles using GitHub usernames:

```yaml
author_customization: |
  torvalds: "Focus on architectural decisions and design patterns. This developer prefers concise, high-level feedback."
  defunkt: "Provide educational explanations and learning opportunities. Focus on best practices and code quality fundamentals."
  octocat: "Be welcoming and provide clear explanations. Focus on project conventions and coding standards."
```

### Usage in Workflow

```yaml
- uses: drew2a/ai-review@v1
  with:
    # ... other parameters ...
    author_customization: |
      torvalds: "Focus on performance and security concerns"
      defunkt: "Educational feedback welcomed"
```

## License

Released under the [MIT License](LICENSE).
