from review import create_header, has_system_role


def test_has_system_role():
    assert has_system_role('gpt-4o')
    assert not has_system_role('o1')


def test_openai_create_header():
    model = 'gpt-4o'
    expected = {
        'Api-Version': '1.0',
        'Authorization': 'Bearer example_key',
        'Content-Type': 'application/json',
        'api-key': 'example_key'
    }
    assert create_header(model, 'example_key', '1.0') == expected


def test_claude_create_header():
    model = 'claude-3-5-sonnet'
    expected = {
        'anthropic-version': '1.0',
        'Content-Type': 'application/json',
        'x-api-key': 'example_key'
    }
    assert create_header(model, 'example_key', '1.0') == expected
