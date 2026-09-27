"""Requisitos de experiência no modo normal do provider."""

from .conftest import MONTH, TICKET, poll_report, request_report, stream_suggestion, timed


def test_f1_complete_result_within_3s(client, provider):
    response, elapsed = timed(lambda: client.post("/tickets/classification", json=TICKET))

    assert response.status_code == 200
    assert response.json() == {"ticket_id": "TK-00042", "category": "delivery", "priority": "high"}
    assert elapsed <= 3


def test_f4_complete_result_within_3s(client, provider):
    response, elapsed = timed(lambda: client.post("/tickets/extraction", json=TICKET))

    assert response.status_code == 200
    assert response.json() == {"ticket_id": "TK-00042", "order_number": "#481516", "product": None}
    assert elapsed <= 3


def test_f2_first_chunk_within_1_5s_and_before_half_of_total(client, provider):
    result = stream_suggestion(client)

    assert result["status"] == 200
    assert result["content_type"].startswith("text/event-stream")
    assert result["first_chunk_s"] <= 1.5
    assert result["first_chunk_s"] < result["total_s"] / 2
    assert result["events"][-1] == ("end", {"ticket_id": "TK-00042"})
    assert sum(1 for event, _ in result["events"] if event == "message") > 10  # chega aos poucos


def test_f3_month_accepted_within_1s_and_complete_later(client, provider):
    accepted, elapsed = request_report(client, MONTH)

    assert accepted.status_code == 202
    assert elapsed <= 1
    assert accepted.headers["location"].startswith("/reports/topics/status/")
    assert int(accepted.headers["retry-after"]) > 0

    status, _ = poll_report(client, accepted.headers["location"], timeout_s=180)
    assert status.status_code == 303
    report = client.get(status.headers["location"])
    assert report.status_code == 200
    body = report.json()
    assert body["total_tickets"] == 5000
    assert sum(topic["count"] for topic in body["topics"]) == 5000

    topics_calls = provider.calls("topics")
    assert len(topics_calls) == 34  # 5.000 tickets em lotes de 150
    assert all(call["status"] == 200 for call in topics_calls)


def test_unknown_report_is_404(client):
    assert client.get("/reports/topics/status/nao-existe").status_code == 404
    assert client.get("/reports/topics/nao-existe").status_code == 404
