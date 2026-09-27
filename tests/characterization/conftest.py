"""Suíte de caracterização: fixa o comportamento observável da v1-coupled pela borda.

Roda contra o compose no ar. Os valores esperados ficam em `golden/`, gravados
a partir da aplicação recebida (ver record_golden.py).
"""

import json
import os
from pathlib import Path

import httpx
import pytest

HELPDESK_URL = os.environ.get("HELPDESK_URL", "http://localhost:8000")
PROVIDER_URL = os.environ.get("PROVIDER_URL", "http://localhost:8090")
GOLDEN_DIR = Path(__file__).parent / "golden"
TICKETS_FILE = Path(__file__).parents[2] / "data" / "tickets.jsonl"


def load_golden(name: str):
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def ticket_text(ticket_id: str) -> str:
    with TICKETS_FILE.open(encoding="utf-8") as file:
        for line in file:
            ticket = json.loads(line)
            if ticket["id"] == ticket_id:
                return ticket["text"]
    raise KeyError(ticket_id)


@pytest.fixture(scope="session", autouse=True)
def provider_normal():
    """Garante o provider simulado no modo normal antes da suíte."""
    httpx.post(f"{PROVIDER_URL}/admin/reset", timeout=10).raise_for_status()


@pytest.fixture(scope="session")
def client():
    # A borda encerra em 30 s; o timeout do cliente fica acima disso para
    # que um 504 da borda apareça como falha de asserção, não como erro do cliente.
    with httpx.Client(base_url=HELPDESK_URL, timeout=60) as http:
        yield http


# ---------- contratos novos da main (streaming e assíncrono) ----------

def read_sse(response: httpx.Response) -> list[tuple[str, dict]]:
    """Lê um stream SSE inteiro como [(evento, dados)]; evento padrão é 'message'."""
    events, event = [], "message"
    for line in response.iter_lines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            events.append((event, json.loads(line.split(":", 1)[1])))
            event = "message"
    return events


def run_report(client: httpx.Client, period: dict, timeout_s: float = 120) -> httpx.Response:
    """Pede o relatório, acompanha a URL de status até o 303 e devolve a resposta do resultado."""
    import time

    accepted = client.post("/reports/topics", json=period)
    assert accepted.status_code == 202, accepted.text
    status_url = accepted.headers["location"]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = client.get(status_url, follow_redirects=False)
        if status.status_code == 303:
            return client.get(status.headers["location"])
        assert status.status_code == 200, status.text
        assert status.json()["state"] in ("pending", "running"), status.json()
        time.sleep(1)
    raise AssertionError(f"relatório não terminou em {timeout_s} s")
