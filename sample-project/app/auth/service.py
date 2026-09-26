from app.users.service import find_by_email


def authenticate(email: str, password: str) -> bool:
    user = find_by_email(email)
    return user is not None and password == "demo-password"
