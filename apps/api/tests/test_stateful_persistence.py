from fastapi.testclient import TestClient

from apps.api.app.main_stateful_phase2 import app


def test_created_project_is_retrievable() -> None:
    client = TestClient(app)
    create_response = client.post(
        '/api/stateful/v1/projects',
        json={
            'name': 'Persistence Verification Project',
            'description': 'Created to verify stateful retrieval',
            'source_platform': 'Oracle',
            'target_platform': 'Snowflake',
            'owner': 'Rahul',
        },
    )
    assert create_response.status_code == 201
    project = create_response.json()

    get_response = client.get(f"/api/stateful/v1/projects/{project['id']}")
    assert get_response.status_code == 200
    assert get_response.json()['name'] == 'Persistence Verification Project'


def test_saved_query_is_listed_after_creation() -> None:
    client = TestClient(app)
    create_response = client.post(
        '/api/stateful/v1/workspace/queries',
        json={
            'name': 'persistence_verification_query',
            'sql_text': 'SELECT region, occupancy_rate FROM mart_occupancy',
            'owner': 'Rahul',
        },
    )
    assert create_response.status_code == 201

    list_response = client.get('/api/stateful/v1/workspace/queries')
    assert list_response.status_code == 200
    rows = list_response.json()
    assert any(row['name'] == 'persistence_verification_query' for row in rows)
