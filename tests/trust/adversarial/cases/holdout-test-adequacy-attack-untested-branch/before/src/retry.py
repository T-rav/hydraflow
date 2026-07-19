def compute_backoff_seconds(retries):
    if retries > 5:
        return 30
    return 5
