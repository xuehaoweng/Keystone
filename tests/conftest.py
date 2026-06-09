import pytest

from app.config import reload_config


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config cache before and after each test to prevent state leakage."""
    reload_config()
    yield
    reload_config()
