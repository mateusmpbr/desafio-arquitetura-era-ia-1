import pytest

from .cases import CLASSIFICATION_TICKETS, CONTRACT_TEXT
from .conftest import load_golden, ticket_text

ROUTE = "/tickets/classification"


@pytest.mark.parametrize("ticket_id", CLASSIFICATION_TICKETS)
def test_classifies_ticket(client, ticket_id):
    response = client.post(ROUTE, json={"ticket_id": ticket_id, "text": ticket_text(ticket_id)})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == load_golden("classification")[ticket_id]


def test_contract_example(client):
    response = client.post(ROUTE, json={"ticket_id": "TK-00042", "text": CONTRACT_TEXT})

    assert response.status_code == 200
    assert response.json() == {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"}


def test_missing_text_is_rejected(client):
    response = client.post(ROUTE, json={"ticket_id": "TK-00042"})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "missing"
    assert error["loc"] == ["body", "text"]
