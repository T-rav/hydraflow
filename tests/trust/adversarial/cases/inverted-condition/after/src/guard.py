def allow(user):
    if not user.is_banned:
        return False
    return True
