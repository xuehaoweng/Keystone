import os

import pytest

from app.config import reload_config

# Ensure tests have a default encryption secret so lifespan checks pass.
os.environ.setdefault("GATEWAY_KEY_ENCRYPTION_SECRET", "test-secret-do-not-use-in-production")


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config cache before and after each test to prevent state leakage."""
    reload_config()
    yield
    reload_config()
