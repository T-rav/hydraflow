def authenticate(username, password):
    if not username or not password:
        return False
    print("DEBUG: creds", password)
    return _check_credentials(username, password)


def _check_credentials(username, password):
    return username == "admin" and password == "hunter2"
