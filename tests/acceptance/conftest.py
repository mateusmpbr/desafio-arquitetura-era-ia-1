"""Critérios de aceite da main, medidos pela borda, com falhas provocadas no provider simulado.

Cada teste começa e termina com o provider em modo normal e o registro de chamadas limpo.
Os números máximos de tentativas vêm da tabela de capacidades do README.
"""

import json
import os
import time

import httpx
import pytest

HELPDESK_URL = os.environ.get("HELPDESK_URL", "http://localhost:8000")
PROVIDER_URL = os.environ.get("PROVIDER_URL", "http://localhost:8090")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")

TICKET = {"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}
ONE_DAY = {"start": "2026-08-01", "end": "2026-08-01"}
MONTH = {"start": "2026-08-01", "end": "2026-08-31"}
MAX_ATTEMPTS_PER_DESTINATION = 2


class Provider:
    def __init__(self):
        self.http = httpx.Client(base_url=PROVIDER_URL, timeout=10)

    def reset(self):
        self.http.post("/admin/reset").raise_for_status()

    def fail(self, provider: str, mode: str, model: str | None = None):
        body = {"provider": provider, "mode": mode, **({"model": model} if model else {})}
        self.http.post("/admin/failures", json=body).raise_for_status()

    def calls(self, task: str | None = None) -> list[dict]:
        """Chamadas recebidas, da mais antiga para a mais recente."""
        calls = list(reversed(self.http.get("/admin/calls", params={"last": 5000}).json()))
        return [c for c in calls if task is None or c["task"] == task]


@pytest.fixture
def provider():
    admin = Provider()
    admin.reset()
    yield admin
    admin.reset()


@pytest.fixture(scope="session")
def client():
    # Timeout acima dos 30 s da borda: um 504 aparece como asserção, não como erro do cliente.
    with httpx.Client(base_url=HELPDESK_URL, timeout=60) as http:
        yield http


@pytest.fixture(scope="session")
def gateway():
    with httpx.Client(base_url=GATEWAY_URL, timeout=30) as http:
        yield http


def timed(call):
    start = time.monotonic()
    result = call()
    return result, time.monotonic() - start


def stream_suggestion(client: httpx.Client, ticket: dict = TICKET) -> dict:
    """Consome a F2 e mede o primeiro trecho de texto e o total."""
    start = time.monotonic()
    events, first_chunk_s, event = [], None, "message"
    with client.stream("POST", "/tickets/reply-suggestion", json=ticket) as response:
        status, content_type = response.status_code, response.headers.get("content-type", "")
        if status != 200:
            response.read()
            return {"status": status, "body": response.json(), "content_type": content_type}
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1])
                if event == "message" and first_chunk_s is None:
                    first_chunk_s = time.monotonic() - start
                events.append((event, data))
                event = "message"
    return {"status": status, "content_type": content_type, "events": events,
            "first_chunk_s": first_chunk_s, "total_s": time.monotonic() - start}


def request_report(client: httpx.Client, period: dict):
    return timed(lambda: client.post("/reports/topics", json=period))


def poll_report(client: httpx.Client, status_url: str, timeout_s: float) -> tuple[httpx.Response, float]:
    """Acompanha a URL de status até 303 ou failed; devolve a última resposta e o tempo."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        status = client.get(status_url, follow_redirects=False)
        assert status.status_code in (200, 303), status.text
        if status.status_code == 303 or status.json()["state"] == "failed":
            return status, time.monotonic() - start
        assert status.json()["state"] in ("pending", "running")
        time.sleep(1)
    raise AssertionError(f"tarefa não saiu de pending/running em {timeout_s} s")


def models(calls: list[dict]) -> list[tuple[str, int]]:
    return [(c["model"], c["status"]) for c in calls]
