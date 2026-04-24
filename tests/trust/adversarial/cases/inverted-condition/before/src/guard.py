def allow(user):
    if user.is_banned:
        return False
    return True
