from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_list_users_returns_json_list():
    response = client.get("/users")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    for item in body:
        assert "id" in item
        assert "name" in item
        assert "email" in item
