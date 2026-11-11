from sqlalchemy.engine import make_url


def require_test_url(value: str | None) -> str:
    if not value:
        raise RuntimeError("Set TEST_DATABASE_URL explicitly: these tests destroy the target schema.")
    try:
        url = make_url(value)
    except Exception as exc:
        raise RuntimeError("Invalid TEST_DATABASE_URL (value redacted).") from None
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith("_test"):
        raise RuntimeError("Refusing schema reset: the PostgreSQL database name must end in _test.")
    return value
