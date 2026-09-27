"""Grava os valores esperados a partir da aplicação no ar.

Executado uma única vez contra a v1-coupled. Regravar muda o que a suíte fixa,
então não faz parte do fluxo normal de testes.

    python tests/characterization/record_golden.py
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from cases import (CLASSIFICATION_TICKETS, CONTRACT_TEXT, EMPTY_PERIOD,  # noqa: E402
                   EXTRACTION_TICKETS, REPORT_PERIOD, SUGGESTION_TICKET)
from conftest import GOLDEN_DIR, HELPDESK_URL, PROVIDER_URL, ticket_text  # noqa: E402


def save(name, data):
    GOLDEN_DIR.mkdir(exist_ok=True)
    (GOLDEN_DIR / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")


def main():
    httpx.post(f"{PROVIDER_URL}/admin/reset", timeout=10).raise_for_status()
    with httpx.Client(base_url=HELPDESK_URL, timeout=60) as http:
        def post(path, body):
            response = http.post(path, json=body)
            response.raise_for_status()
            return response.json()

        save("classification", {tid: post("/tickets/classification",
                                          {"ticket_id": tid, "text": ticket_text(tid)})
                                for tid in CLASSIFICATION_TICKETS})
        save("classification_contract", post("/tickets/classification",
                                             {"ticket_id": "TK-00042", "text": CONTRACT_TEXT}))
        save("extraction", {tid: post("/tickets/extraction", {"ticket_id": tid, "text": ticket_text(tid)})
                            for tid in EXTRACTION_TICKETS})
        save("suggestion", post("/tickets/reply-suggestion",
                                {"ticket_id": SUGGESTION_TICKET, "text": ticket_text(SUGGESTION_TICKET)}))
        save("report", post("/reports/topics", REPORT_PERIOD))
        save("report_empty", post("/reports/topics", EMPTY_PERIOD))


if __name__ == "__main__":
    main()
