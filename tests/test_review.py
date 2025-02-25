from review import get_model, supported_models


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
