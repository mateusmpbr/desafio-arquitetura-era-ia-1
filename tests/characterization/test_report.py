from .cases import EMPTY_PERIOD, REPORT_PERIOD
from .conftest import load_golden

ROUTE = "/reports/topics"


def test_topics_report_across_batches(client):
    response = client.post(ROUTE, json=REPORT_PERIOD)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert body == load_golden("report")
    assert body["total_tickets"] == 274
    assert sum(topic["count"] for topic in body["topics"]) == 274
    assert all(len(topic["examples"]) <= 3 for topic in body["topics"])


def test_period_without_tickets(client):
    response = client.post(ROUTE, json=EMPTY_PERIOD)

    assert response.status_code == 200
    assert response.json() == load_golden("report_empty")


def test_start_after_end_is_rejected(client):
    response = client.post(ROUTE, json={"start": "2026-08-31", "end": "2026-08-01"})

    assert response.status_code == 422
    assert response.json() == {"detail": "A data inicial é posterior à data final"}


def test_invalid_date_is_rejected(client):
    response = client.post(ROUTE, json={"start": "2026-13-01", "end": "2026-08-31"})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "start"]
