import argparse
import pytest
from unittest import mock
from unittest.mock import patch

from review import get_model, process_review, supported_models


def test_openai_create_header():
    """ Test OpenAI header creation """
    model = get_model('gpt-4o')

    expected = {
        'Api-Version': '1.0',
        'Authorization': 'Bearer example_key',
        'Content-Type': 'application/json',
        'api-key': 'example_key'
    }

    assert supported_models[model]['header']('example_key', '1.0') == expected


def test_claude_create_header():
    """ Test Claude header creation """
    model = get_model('claude-3-5-sonnet')

    expected = {
        'anthropic-version': '1.0',
        'Content-Type': 'application/json',
        'x-api-key': 'example_key'
    }
    assert supported_models[model]['header']('example_key', '1.0') == expected


def test_get_model_unsupported_pattern():
    """ Test get_model raises ValueError for unsupported patterns """
    with pytest.raises(ValueError) as exc_info:
        get_model('unsupported-model')
    expected_message = "Unsupported model pattern: unsupported-model. Supported patterns are: ['^gpt-4', '^o1', '^claude-3']"
    assert str(exc_info.value) == expected_message


@patch('builtins.open', mock.mock_open(read_data="prompt"))
@patch('requests.post')
def test_process_review(mock_post):
    """ Test the process_review function """
    diff_content = "Sample diff content"
    args = argparse.Namespace(
        api_endpoint='https://api.test.com',
        api_key='test_key',
        api_version='v1',
        llm_model='gpt-4o',
        github_token='gh_token',
        debug='false',
        add_review_resolution='false'
    )

    expected_response = 'Review content generated by LLM.'

    mock_response = mock.Mock()
    mock_response.json.return_value = {'choices': [{'message': {'content': expected_response}}]}
    mock_response.raise_for_status = mock.Mock()
    mock_post.return_value = mock_response

    result = process_review(diff_content, args)

    assert result == expected_response
    mock_post.assert_called_once_with(
        args.api_endpoint,
        headers={
            'Authorization': f"Bearer {args.api_key}",
            "api-key": args.api_key,
            'Api-Version': args.api_version,
            'Content-Type': 'application/json'
        },
        json={
            "model": args.llm_model,
            "messages": [
                {"role": 'system', "content": "prompt"},
                {"role": "user", "content": "prompt"}
            ]
        }
    )
