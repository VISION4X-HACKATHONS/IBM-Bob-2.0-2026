from app.database import UserRecord, USERS


def find_by_email(email: str) -> UserRecord | None:
    return next((user for user in USERS if user.email == email), None)
