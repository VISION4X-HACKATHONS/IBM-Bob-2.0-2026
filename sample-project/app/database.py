from dataclasses import dataclass


@dataclass
class UserRecord:
    id: int
    email: str
    password_hash: str


USERS = [UserRecord(1, "demo@example.com", "hashed-password")]
