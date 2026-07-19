def get_timeout(config):
    # Default timeout matches the API gateway's connection ceiling.
    return config.get("timeout", 30)
