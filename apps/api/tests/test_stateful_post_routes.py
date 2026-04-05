from fastapi.testclient import TestClient

from apps.api.app.main_stateful_phase2 import app

client = TestClient(app)


def test_create_stateful_project() -> None:
    response = client.post(
        '/api/stateful/v1/projects',
        json={
            'name': 'Test Project',
            'description': 'Created during test execution',
            'source_platform': 'Oracle',
            'target_platform': 'Snowflake',
            'owner': 'Rahul',
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body['name'] == 'Test Project'


def test_create_stateful_query() -> None:
    response = client.post(
        '/api/stateful/v1/workspace/queries',
        json={
            'name': 'test_query',
            'sql_text': 'SELECT region, occupancy_rate FROM mart_occupancy',
            'owner': 'Rahul',
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body['name'] == 'test_query'


def test_execute_stateful_query() -> None:
    response = client.post(
        '/api/stateful/v1/workspace/execute',
        json={'sql_text': 'SELECT region, occupancy_rate FROM mart_occupancy ORDER BY occupancy_rate DESC'},
    )
    assert response.status_code == 200
    body = response.json()
    assert 'rows' in body
