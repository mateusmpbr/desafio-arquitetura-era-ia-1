from typing import Protocol


class CompletionGateway(Protocol):
    """O que as features precisam de um modelo: completar um prompt numa capacidade lógica.

    Qual provider e qual modelo físico atendem a capacidade é decisão do AI Gateway.
    """

    def complete(self, capability: str, prompt: str, max_tokens: int | None = None) -> str: ...
