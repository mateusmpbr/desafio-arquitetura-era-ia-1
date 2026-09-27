import pytest

from .cases import EXTRACTION_TICKETS
from .conftest import load_golden, ticket_text

ROUTE = "/tickets/extraction"


@pytest.mark.parametrize("ticket_id", EXTRACTION_TICKETS)
def test_extracts_order_data(client, ticket_id):
    response = client.post(ROUTE, json={"ticket_id": ticket_id, "text": ticket_text(ticket_id)})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == load_golden("extraction")[ticket_id]


def test_invoice_number_is_not_taken_as_order(client):
    # TK-00002 cita a nota fiscal 530720 antes do pedido #605065.
    response = client.post(ROUTE, json={"ticket_id": "TK-00002", "text": ticket_text("TK-00002")})

    assert response.json()["order_number"] == "#605065"


def test_missing_ticket_id_is_rejected(client):
    response = client.post(ROUTE, json={"text": "Quero trocar o pedido #605065"})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "missing"
    assert error["loc"] == ["body", "ticket_id"]
