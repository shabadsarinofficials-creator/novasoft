"""Basic smoke tests — run against a configured DATABASE_URL."""
import os
import pytest
from fastapi.testclient import TestClient

# Ensure env before import
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-32c")
os.environ.setdefault("ADMIN_EMAIL", "testadmin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "TestAdminPass123!")

from backend.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["app"] == "BizSuite"


def test_docs_available():
    r = client.get("/docs")
    assert r.status_code == 200