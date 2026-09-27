from .cases import SUGGESTION_TICKET
from .conftest import load_golden, read_sse, ticket_text

ROUTE = "/tickets/reply-suggestion"


def test_suggests_reply(client):
    # main: a sugestão chega por streaming (SSE); o texto completo é o mesmo da v1.
    with client.stream("POST", ROUTE, json={"ticket_id": SUGGESTION_TICKET,
                                            "text": ticket_text(SUGGESTION_TICKET)}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = read_sse(response)

    chunks = [data["chunk"] for event, data in events if event == "message"]
    assert "".join(chunks) == load_golden("suggestion")["suggestion"]
    assert events[-1] == ("end", {"ticket_id": SUGGESTION_TICKET})


def test_empty_ticket_id_is_rejected(client):
    response = client.post(ROUTE, json={"ticket_id": "", "text": "Meu pedido não chegou"})

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "string_too_short"
    assert error["loc"] == ["body", "ticket_id"]
