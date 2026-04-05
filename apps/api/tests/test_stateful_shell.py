from fastapi.testclient import TestClient

from apps.api.app.main_stateful_phase2 import app

client = TestClient(app)


def test_stateful_health() -> None:
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_stateful_projects_route() -> None:
    response = client.get('/api/stateful/v1/projects')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_stateful_discovery_route() -> None:
    response = client.get('/api/stateful/v1/discovery/runs')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_stateful_conversion_route() -> None:
    response = client.get('/api/stateful/v1/conversion/items')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_stateful_validation_route() -> None:
    response = client.get('/api/stateful/v1/validation/runs')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_stateful_workspace_route() -> None:
    response = client.get('/api/stateful/v1/workspace/queries')
    assert response.status_code == 200
    assert isinstance(response.json(), list)
