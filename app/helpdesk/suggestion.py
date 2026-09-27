from .ports import CompletionGateway
from .schemas import ReplySuggestion, TicketInput


class ReplySuggester:
    def __init__(self, gateway: CompletionGateway, capability: str, max_tokens: int):
        self._gateway = gateway
        self._capability = capability
        self._max_tokens = max_tokens

    def suggest(self, ticket: TicketInput) -> ReplySuggestion:
        text = self._gateway.complete(self._capability, f"TASK: suggest\n{ticket.text}", self._max_tokens)
        return ReplySuggestion(ticket_id=ticket.ticket_id, suggestion=text)
