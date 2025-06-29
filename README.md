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

## License

Released under the [MIT License](LICENSE).
