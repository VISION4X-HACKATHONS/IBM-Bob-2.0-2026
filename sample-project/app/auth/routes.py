from fastapi import APIRouter

from app.auth.service import authenticate

router = APIRouter(prefix="/auth")


@router.post("/login")
def login(email: str, password: str) -> dict[str, str]:
    if not authenticate(email, password):
        return {"error": "invalid credentials"}
    return {"token": "sample-session-token"}


@router.post("/register")
def register(email: str, password: str) -> dict[str, str]:
    return {"status": "created", "email": email}
