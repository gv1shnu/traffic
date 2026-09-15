import os
import tempfile

# Tests always get their own database and storage directory, before application imports.
ROOT = tempfile.mkdtemp(prefix="traffic-tests-")
os.environ["STORAGE_ROOT"] = ROOT
os.environ["DATABASE_URL"] = f"sqlite:///{ROOT}/test.db"
os.environ["OCR_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from packages.shared.db import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
