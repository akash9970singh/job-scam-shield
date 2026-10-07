import pytest

from app import auth


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own empty database and fresh rate limits."""
    monkeypatch.setenv("SHIELD_DB_PATH", str(tmp_path / "test.db"))
    auth.login_limiter.reset()
    auth.report_limiter.reset()
