def normalize_email(value: str) -> str:
    return value.strip().lower()


def validate_email(value: str) -> bool:
    return "@" in normalize_email(value)
