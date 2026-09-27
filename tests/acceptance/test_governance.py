"""Roteiro de governança: recusas do gateway não chegam ao provider."""

import os

from .conftest import TICKET

MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-gateway-master-0001")
BUDGET_KEY = os.environ.get("GATEWAY_BUDGET_DEMO_KEY", "sk-governance-budget-0001")
RPM_KEY = os.environ.get("GATEWAY_RPM_DEMO_KEY", "sk-governance-rpm-0001")

REQUEST = {"model": "ticket-classification",
           "messages": [{"role": "user", "content": f"TASK: classify\n{TICKET['text']}"}]}


def classify_with(gateway, key):
    return gateway.post("/v1/chat/completions", json=REQUEST, headers={"Authorization": f"Bearer {key}"})


def test_budget_exceeded_is_refused_before_provider(gateway, provider):
    reset = gateway.post("/key/update", json={"key": BUDGET_KEY, "spend": 0},
                         headers={"Authorization": f"Bearer {MASTER_KEY}"})
    assert reset.status_code == 200

    first = classify_with(gateway, BUDGET_KEY)
    assert first.status_code == 200  # gasta ~US$ 0,00014, acima do orçamento de US$ 0,0001

    refused = [classify_with(gateway, BUDGET_KEY) for _ in range(2)]
    for response in refused:
        assert response.status_code == 429
        assert response.json()["error"]["type"] == "budget_exceeded"
    assert len(provider.calls("classify")) == 1


def test_rate_limit_is_refused_before_provider(gateway, provider):
    responses = [classify_with(gateway, RPM_KEY) for _ in range(4)]

    accepted = [r for r in responses if r.status_code == 200]
    refused = [r for r in responses if r.status_code == 429]
    assert len(accepted) <= 2  # rpm_limit = 2
    assert len(refused) >= 2
    assert all("Rate limit" in r.json()["error"]["message"] for r in refused)
    assert len(provider.calls("classify")) == len(accepted)
