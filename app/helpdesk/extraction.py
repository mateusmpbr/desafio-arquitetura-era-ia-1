import json
import re

from fastapi import HTTPException

from .ports import CompletionGateway
from .schemas import OrderData, TicketInput

ORDER_FORMAT = re.compile(r"^#\d{6}$")


class OrderExtractor:
    def __init__(self, gateway: CompletionGateway, capability: str):
        self._gateway = gateway
        self._capability = capability

    def extract(self, ticket: TicketInput) -> OrderData:
        text = self._gateway.complete(self._capability, f"TASK: extract\n{ticket.text}")
        data = json.loads(text)
        order_number = data.get("order_number")
        if order_number is not None and not ORDER_FORMAT.match(order_number):
            raise HTTPException(status_code=502, detail="Número de pedido em formato inválido")
        return OrderData(ticket_id=ticket.ticket_id, order_number=order_number, product=data.get("product"))
