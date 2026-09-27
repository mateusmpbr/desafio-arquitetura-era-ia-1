import json

from fastapi import HTTPException

from .ports import CompletionGateway
from .schemas import Classification, TicketInput

CATEGORIES = {"delivery", "payment", "exchange_return", "product_defect", "other"}
PRIORITIES = {"low", "medium", "high"}


class TicketClassifier:
    def __init__(self, gateway: CompletionGateway, capability: str):
        self._gateway = gateway
        self._capability = capability

    def classify(self, ticket: TicketInput) -> Classification:
        text = self._gateway.complete(self._capability, f"TASK: classify\n{ticket.text}")
        data = json.loads(text)
        if data.get("category") not in CATEGORIES or data.get("priority") not in PRIORITIES:
            raise HTTPException(status_code=502, detail="Classificação fora dos valores permitidos")
        return Classification(ticket_id=ticket.ticket_id, **data)
