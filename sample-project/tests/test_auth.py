from app.auth.service import authenticate


def test_demo_user_can_authenticate():
    assert authenticate("demo@example.com", "demo-password") is True


def test_unknown_user_is_rejected():
    assert authenticate("unknown@example.com", "demo-password") is False
