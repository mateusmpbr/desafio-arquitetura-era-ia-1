from .cases import SUGGESTION_TICKET
from .conftest import load_golden, ticket_text

ROUTE = "/tickets/reply-suggestion"


def test_suggests_reply(client):
    response = client.post(ROUTE, json={"ticket_id": SUGGESTION_TICKET, "text": ticket_text(SUGGESTION_TICKET)})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"ticket_id", "suggestion"}
    assert body == load_golden("suggestion")


def test_empty_ticket_id_is_rejected(client):
    response = client.post(ROUTE, json={"ticket_id": "", "text": "Meu pedido não chegou"})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "string_too_short"
    assert error["loc"] == ["body", "ticket_id"]
