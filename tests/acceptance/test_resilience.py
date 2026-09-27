"""Fallback técnico, fallback com modelo fraco e timeouts, provocados no provider simulado."""

import pytest

from .conftest import (MAX_ATTEMPTS_PER_DESTINATION, ONE_DAY, TICKET, models, poll_report,
                       request_report, stream_suggestion, timed)

# capacidade -> (tarefa, provider primário, modelo primário, destino equivalente, destino fraco)
CAPABILITIES = {
    "classification": ("classify", "openai", "gpt-fake-large", "claude-fake-large", "gpt-fake-mini"),
    "suggestion": ("suggest", "anthropic", "claude-fake-large", "gpt-fake-large", "claude-fake-mini"),
    "report": ("topics", "anthropic", "claude-fake-large", "gpt-fake-large", "claude-fake-mini"),
    "extraction": ("extract", "openai", "gpt-fake-large", "claude-fake-large", None),
}


def call_feature(client, feature):
    """Executa a feature até o fim e devolve (status final, corpo/eventos)."""
    if feature == "classification":
        response = client.post("/tickets/classification", json=TICKET)
        return response.status_code, response.json()
    if feature == "extraction":
        response = client.post("/tickets/extraction", json=TICKET)
        return response.status_code, response.json()
    if feature == "suggestion":
        result = stream_suggestion(client)
        return result["status"], result.get("events", result.get("body"))
    accepted, _ = request_report(client, ONE_DAY)
    assert accepted.status_code == 202
    status, _ = poll_report(client, accepted.headers["location"], timeout_s=60)
    if status.status_code == 303:
        return 200, client.get(status.headers["location"]).json()
    return 500, status.json()


@pytest.mark.parametrize("feature", CAPABILITIES)
def test_primary_down_falls_back_to_equivalent_on_other_provider(client, provider, feature):
    task, primary_provider, primary, equivalent, _ = CAPABILITIES[feature]
    provider.fail(primary_provider, "error_500", model=primary)

    status, _ = call_feature(client, feature)

    assert status == 200
    calls = models(provider.calls(task))
    attempts_on_primary = [c for c in calls if c[0] == primary]
    assert 1 <= len(attempts_on_primary) <= MAX_ATTEMPTS_PER_DESTINATION
    assert all(code == 500 for _, code in attempts_on_primary)
    assert calls[len(attempts_on_primary):] == [(equivalent, 200)]


@pytest.mark.parametrize("feature", CAPABILITIES)
def test_both_large_down_follows_fallback_table(client, provider, feature):
    task, _, primary, equivalent, weak = CAPABILITIES[feature]
    provider.fail("openai", "error_500", model="gpt-fake-large")
    provider.fail("anthropic", "error_500", model="claude-fake-large")

    status, body = call_feature(client, feature)
    calls = models(provider.calls(task))

    assert sum(1 for m, _ in calls if m == primary) <= MAX_ATTEMPTS_PER_DESTINATION
    assert sum(1 for m, _ in calls if m == equivalent) <= MAX_ATTEMPTS_PER_DESTINATION
    if weak:
        # Tabela de fallback: responde com o modelo mini.
        assert status == 200
        assert calls[-1] == (weak, 200)
    else:
        # F4: falha explícita; o mini nunca é chamado para extração.
        assert status == 503
        assert body["capability"] == "order-extraction"
        assert "indisponível" in body["detail"]
        assert all("mini" not in m for m, _ in calls)


def test_f3_with_both_providers_down_fails_visibly_within_60s(client, provider):
    provider.fail("openai", "error_500")
    provider.fail("anthropic", "error_500")

    accepted, elapsed = request_report(client, {"start": "2026-08-01", "end": "2026-08-31"})
    assert accepted.status_code == 202 and elapsed <= 1

    status, waited = poll_report(client, accepted.headers["location"], timeout_s=60)
    assert status.status_code == 200
    body = status.json()
    assert body["state"] == "failed"
    assert body["reason"]
    assert waited <= 60


def test_f1_with_primary_hung_answers_within_15s(client, provider):
    provider.fail("openai", "timeout", model="gpt-fake-large")

    response, elapsed = timed(lambda: client.post("/tickets/classification", json=TICKET))

    assert response.status_code in (200, 503)
    assert response.status_code != 504
    assert elapsed <= 15


def test_f4_with_primary_hung_answers_within_15s(client, provider):
    provider.fail("openai", "timeout", model="gpt-fake-large")

    response, elapsed = timed(lambda: client.post("/tickets/extraction", json=TICKET))

    assert response.status_code in (200, 503)
    assert elapsed <= 15


def test_f2_midstream_failure_arrives_as_error_event(client, provider):
    provider.fail("anthropic", "midstream_error", model="claude-fake-large")

    result = stream_suggestion(client)

    assert result["status"] == 200
    assert result["content_type"].startswith("text/event-stream")
    chunks = [data for event, data in result["events"] if event == "message"]
    assert chunks, "o texto parcial chega antes do erro"
    assert result["events"][-1] == ("error", {"ticket_id": "TK-00042", "message": "A geração foi interrompida"})
