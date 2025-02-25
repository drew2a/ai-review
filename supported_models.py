supported_models = {
    '^gpt-4': {
        'has_system': True,
        'header': lambda key, version: {
            'Authorization': f"Bearer {key}",  # for OpenAPI
            "api-key": key,  # for Azure
            'Api-Version': version,
            'Content-Type': 'application/json'
        }
    },
    '^o1': {
        'has_system': False,
        'header': lambda key, version: {
            'Authorization': f"Bearer {key}",  # for OpenAPI
            "api-key": key,  # for Azure
            'Api-Version': version,
            'Content-Type': 'application/json'
        }
    },
    '^claude': {
        'has_system': True,
        'header': lambda key, version: {
            "x-api-key": key,
            'anthropic-version': version,
            'Content-Type': 'application/json'
        }
    }
}
