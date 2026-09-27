from collections.abc import Iterator
from typing import Protocol

from .schemas import ReportJob


class CapabilityUnavailable(Exception):
    """O gateway não conseguiu atender a capacidade (destinos esgotados, timeout, recusa)."""

    def __init__(self, capability: str, reason: str):
        super().__init__(f"{capability}: {reason}")
        self.capability = capability
        self.reason = reason


class CompletionGateway(Protocol):
    """O que as features precisam de um modelo: completar um prompt numa capacidade lógica.

    Qual provider e qual modelo físico atendem a capacidade é decisão do AI Gateway.
    Falhas chegam como CapabilityUnavailable, inclusive no meio de um stream.
    """

    def complete(self, capability: str, prompt: str, max_tokens: int | None = None) -> str: ...

    def stream(self, capability: str, prompt: str, max_tokens: int | None = None) -> Iterator[str]: ...


class JobStore(Protocol):
    """Estado das tarefas assíncronas. Em memória hoje; persistir é trocar o adaptador."""

    def create(self) -> ReportJob: ...

    def save(self, job: ReportJob) -> None: ...

    def get(self, job_id: str) -> ReportJob | None: ...
