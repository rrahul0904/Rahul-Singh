from fastapi.testclient import TestClient

from apps.api.app.main_integrated import app

client = TestClient(app)


def test_integrated_health() -> None:
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_integrated_projects_route() -> None:
    response = client.get('/api/v1/projects')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_integrated_discovery_route() -> None:
    response = client.get('/api/v1/discovery/runs')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_integrated_conversion_route() -> None:
    response = client.get('/api/v1/conversion/items')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_integrated_validation_route() -> None:
    response = client.get('/api/v1/validation/runs')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_integrated_workspace_route() -> None:
    response = client.get('/api/v1/workspace/queries')
    assert response.status_code == 200
    assert isinstance(response.json(), list)
