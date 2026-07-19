def compute_backoff_seconds(retries):
    if retries > 5:
        return 30
    if retries > 3:
        return 15
    return 5
