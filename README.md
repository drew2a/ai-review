[![Build and Test](https://github.com/drew2a/ai-review/actions/workflows/ci.yml/badge.svg)](https://github.com/drew2a/ai-review/actions/workflows/ci.yml) [![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)

# AI Code Review Action

A GitHub Action that provides automated code review using AI to analyze pull request changes.

## Features

- Automatically reviews pull request changes using AI
- Provides detailed code suggestions and improvements
- Adds review comments directly to the PR
- Works with any programming language
- Supports different AI models and API endpoints
- Optional review resolution statuses (e.g., "APPROVE", "REQUEST_CHANGES", "COMMENT")
- Debug mode for enhanced logging

## Supported models:

- gpt-4o
- o1
- claude-3-7-sonnet
- claude-3-5-sonnet
- gemini-2.0-flash
- gemini-2.5-flash
- gemini-2.5-pro

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

## Inputs

| Name                    | Description                                               | Required | Default              |
|-------------------------|-----------------------------------------------------------|----------|----------------------|
| `api_endpoint`          | LLM API endpoint                                          | true     | -                    |
| `api_key`               | LLM API key                                               | true     | -                    |
| `api_version`           | LLM API version                                           | false    | `2023-12-01-preview` |
| `llm_model`             | LLM Model used for review                                 | false    | `gpt-4o`             |
| `debug`                 | Enable debug mode (true/false)                            | false    | `false`              |
| `add_review_resolution` | Add review resolution (APPROVE, REQUEST_CHANGES, COMMENT) | false    | `false`              |
| `add_joke`              | Add a joke to the review comment                          | false    | `false`              |
| `author_customization`  | YAML configuration for customizing reviews based on PR author | false | -                    |
| `github_token`          | GitHub token for authentication                           | true     | -                    |

## Usage

To use this action in your GitHub workflow, add the following step:

```yaml
- uses: drew2a/ai-review@v1
  with:
    api_endpoint: ${{ secrets.LLM_ENDPOINT }}
    api_key: ${{ secrets.LLM_API_KEY }}
    api_version: ${{ secrets.LLM_API_VERSION }}
    llm_model: ${{ secrets.LLM_MODEL }}

    github_token: ${{ secrets.GITHUB_TOKEN }}

    debug: false
    add_review_resolution: false
    add_joke: false
    author_customization: |
      torvalds: "This is an experienced developer. Focus on architecture and design patterns."
      defunkt: "This is a junior developer. Provide educational feedback and explanations."
```

### Example Workflow

```yaml
name: AI Code Review

on: [ pull_request ]

permissions:
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: drew2a/ai-review@v1
        with:
          api_endpoint: ${{ secrets.LLM_ENDPOINT }}
          api_key: ${{ secrets.LLM_API_KEY }}
          api_version: ${{ secrets.LLM_API_VERSION }}
          llm_model: ${{ secrets.LLM_MODEL }}

          github_token: ${{ secrets.GITHUB_TOKEN }}

          debug: true
          add_review_resolution: false
          add_joke: false
```

## Author Customization

The `author_customization` parameter allows you to customize the review behavior based on the PR author's GitHub username. This is useful for providing different types of feedback for team members with different experience levels or roles.

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
