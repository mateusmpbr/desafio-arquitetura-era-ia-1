from collections.abc import Iterator

from .ports import CompletionGateway
from .schemas import TicketInput


class ReplySuggester:
    def __init__(self, gateway: CompletionGateway, capability: str, max_tokens: int):
        self._gateway = gateway
        self._capability = capability
        self._max_tokens = max_tokens

    def stream(self, ticket: TicketInput) -> Iterator[str]:
        """Trechos da sugestão na ordem em que o modelo os gera."""
        return self._gateway.stream(self._capability, f"TASK: suggest\n{ticket.text}", self._max_tokens)
