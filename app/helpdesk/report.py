import json
from collections.abc import Callable
from datetime import date

from fastapi import HTTPException

from .ports import CompletionGateway
from .schemas import PeriodInput, Topic, TopicsReport

TicketLoader = Callable[[date, date], list[dict]]


class TopicsReporter:
    def __init__(self, gateway: CompletionGateway, capability: str, load_tickets: TicketLoader,
                 batch_size: int, max_tokens: int):
        self._gateway = gateway
        self._capability = capability
        self._load_tickets = load_tickets
        self._batch_size = batch_size
        self._max_tokens = max_tokens

    def topics(self, period: PeriodInput) -> TopicsReport:
        if period.start > period.end:
            raise HTTPException(status_code=422, detail="A data inicial é posterior à data final")

        selected = self._load_tickets(period.start, period.end)

        # O mês inteiro não cabe numa chamada: processa em lotes, um depois do outro.
        totals: dict[str, dict] = {}
        for first in range(0, len(selected), self._batch_size):
            batch = selected[first:first + self._batch_size]
            content = "\n".join(f"[{t['id']}] {t['text']}" for t in batch)
            answer = json.loads(self._gateway.complete(self._capability, f"TASK: topics\n{content}",
                                                       self._max_tokens))
            for item in answer["topics"]:
                current = totals.setdefault(item["topic"], {"count": 0, "examples": []})
                current["count"] += item["count"]
                current["examples"] = (current["examples"] + item["examples"])[:3]

        items = [Topic(topic=name, **data) for name, data in totals.items()]
        items.sort(key=lambda t: (-t.count, t.topic))
        return TopicsReport(start=period.start, end=period.end, total_tickets=len(selected), topics=items)
