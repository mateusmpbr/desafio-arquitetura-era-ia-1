import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date

from fastapi import HTTPException

from .ports import CapabilityUnavailable, CompletionGateway, JobStore
from .schemas import JobState, PeriodInput, ReportJob, Topic, TopicsReport

TicketLoader = Callable[[date, date], list[dict]]

log = logging.getLogger("helpdesk.report")


class TopicsReporter:
    """Relatório de temas como tarefa assíncrona: o pedido só registra a tarefa, e os lotes
    rodam em segundo plano, em paralelo, com o estado exposto pelo JobStore."""

    def __init__(self, gateway: CompletionGateway, capability: str, load_tickets: TicketLoader,
                 jobs: JobStore, batch_size: int, max_tokens: int, concurrency: int):
        self._gateway = gateway
        self._capability = capability
        self._load_tickets = load_tickets
        self._jobs = jobs
        self._batch_size = batch_size
        self._max_tokens = max_tokens
        self._concurrency = concurrency

    def submit(self, period: PeriodInput) -> ReportJob:
        if period.start > period.end:
            raise HTTPException(status_code=422, detail="A data inicial é posterior à data final")
        job = self._jobs.create()
        threading.Thread(target=self._run, args=(job, period), daemon=True).start()
        return job

    def _run(self, job: ReportJob, period: PeriodInput) -> None:
        # Qualquer saída deste método deixa a tarefa em done ou failed: nunca presa em running.
        try:
            job.result = self._build(job, period)
            job.state = JobState.done
        except CapabilityUnavailable as error:
            job.state, job.reason = JobState.failed, f"Modelo indisponível para o relatório: {error.reason}"
        except Exception:
            log.exception("relatório %s falhou", job.id)
            job.state, job.reason = JobState.failed, "Erro inesperado ao montar o relatório"
        self._jobs.save(job)

    def _build(self, job: ReportJob, period: PeriodInput) -> TopicsReport:
        selected = self._load_tickets(period.start, period.end)
        batches = [selected[i:i + self._batch_size] for i in range(0, len(selected), self._batch_size)]
        job.state, job.progress = JobState.running, f"0/{len(selected)}"
        self._jobs.save(job)

        # O mês inteiro não cabe numa chamada: os lotes vão em paralelo, e a primeira falha
        # derruba a tarefa sem esperar os outros (cancela os que ainda não começaram).
        pool = ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix=f"report-{job.id}")
        futures = [pool.submit(self._topics_of, batch) for batch in batches]
        try:
            pending, processed = set(futures), 0
            while pending:
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    future.result()  # propaga a falha do lote
                    processed += len(batches[futures.index(future)])
                job.progress = f"{processed}/{len(selected)}"
                self._jobs.save(job)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        # Agrega na ordem dos lotes, como na versão síncrona: mesmos exemplos, mesmo resultado.
        totals: dict[str, dict] = {}
        for future in futures:
            for item in future.result()["topics"]:
                current = totals.setdefault(item["topic"], {"count": 0, "examples": []})
                current["count"] += item["count"]
                current["examples"] = (current["examples"] + item["examples"])[:3]

        items = [Topic(topic=name, **data) for name, data in totals.items()]
        items.sort(key=lambda t: (-t.count, t.topic))
        return TopicsReport(start=period.start, end=period.end, total_tickets=len(selected), topics=items)

    def _topics_of(self, batch: list[dict]) -> dict:
        content = "\n".join(f"[{t['id']}] {t['text']}" for t in batch)
        return json.loads(self._gateway.complete(self._capability, f"TASK: topics\n{content}", self._max_tokens))
