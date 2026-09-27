import json
import logging
from collections.abc import Iterator
from itertools import chain

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from . import config, tickets
from .adapters.gateway import GatewayClient
from .adapters.job_store import InMemoryJobStore
from .classification import TicketClassifier
from .extraction import OrderExtractor
from .ports import CapabilityUnavailable
from .report import TopicsReporter
from .schemas import Classification, JobState, OrderData, PeriodInput, TicketInput, TopicsReport
from .suggestion import ReplySuggester

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Ponto de composição: o único lugar que conhece os adaptadores concretos.
interactive = GatewayClient(config.GATEWAY_BASE_URL, config.GATEWAY_API_KEY, config.INTERACTIVE_TIMEOUT_S)
batch = GatewayClient(config.GATEWAY_BASE_URL, config.GATEWAY_API_KEY, config.REPORT_CALL_TIMEOUT_S)
jobs = InMemoryJobStore()

classifier = TicketClassifier(interactive, config.CLASSIFICATION_CAPABILITY)
suggester = ReplySuggester(interactive, config.SUGGESTION_CAPABILITY, config.MAX_OUTPUT_TOKENS)
extractor = OrderExtractor(interactive, config.EXTRACTION_CAPABILITY)
reporter = TopicsReporter(batch, config.REPORT_CAPABILITY, tickets.in_period, jobs,
                          config.TICKETS_PER_CALL, config.MAX_OUTPUT_TOKENS, config.REPORT_CONCURRENCY)

app = FastAPI(title="Helpdesk")


@app.exception_handler(CapabilityUnavailable)
def capability_unavailable(request: Request, error: CapabilityUnavailable) -> JSONResponse:
    # Falha explícita e rápida em vez de pendurar a requisição até o 504 da borda.
    return JSONResponse(status_code=503, content={"detail": f"Serviço de IA indisponível: {error.reason}",
                                                  "capability": error.capability})


@app.get("/health")
def health():
    return {"status": "ok"}


# F1: síncrono (ADR 0004)
@app.post("/tickets/classification")
def classify_ticket(ticket: TicketInput) -> Classification:
    return classifier.classify(ticket)


# F2: streaming por SSE (ADR 0004)
@app.post("/tickets/reply-suggestion")
def suggest_reply(ticket: TicketInput) -> StreamingResponse:
    chunks = suggester.stream(ticket)
    # Espera o primeiro trecho antes de responder: se nenhum modelo atender, o cliente
    # recebe um 503 com status HTTP de verdade, e não um stream que já nasce com erro.
    first = next(chunks, "")
    return StreamingResponse(
        sse_suggestion(ticket.ticket_id, chain([first], chunks)),
        media_type="text/event-stream",
        # X-Accel-Buffering: sem ele, a borda (nginx) acumula a resposta e entrega em bloco.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def sse_suggestion(ticket_id: str, chunks: Iterator[str]) -> Iterator[str]:
    try:
        for chunk in chunks:
            if chunk:
                yield sse({"chunk": chunk})
    except CapabilityUnavailable:
        # O 200 já foi enviado: a falha vira um evento dentro do próprio stream.
        yield sse({"ticket_id": ticket_id, "message": "A geração foi interrompida"}, event="error")
        return
    yield sse({"ticket_id": ticket_id}, event="end")


def sse(data: dict, event: str | None = None) -> str:
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data, ensure_ascii=False)}\n\n"


# F4: síncrono (ADR 0004)
@app.post("/tickets/extraction")
def extract_order_data(ticket: TicketInput) -> OrderData:
    return extractor.extract(ticket)


# F3: Asynchronous Request-Reply (ADR 0004)
@app.post("/reports/topics", status_code=202)
def request_topics_report(period: PeriodInput) -> JSONResponse:
    job = reporter.submit(period)
    return JSONResponse(
        status_code=202,
        content={"id": job.id, "state": job.state.value},
        headers={"Location": f"/reports/topics/status/{job.id}",
                 "Retry-After": str(config.REPORT_RETRY_AFTER_S)},
    )


@app.get("/reports/topics/status/{job_id}")
def topics_report_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    if job.state == JobState.done:
        return RedirectResponse(f"/reports/topics/{job.id}", status_code=303)
    body = {"state": job.state.value}
    if job.state == JobState.failed:
        return JSONResponse({**body, "reason": job.reason})
    if job.progress:
        body["progress"] = job.progress
    return JSONResponse(body, headers={"Retry-After": str(config.REPORT_RETRY_AFTER_S)})


@app.get("/reports/topics/{job_id}")
def topics_report_result(job_id: str) -> TopicsReport:
    job = jobs.get(job_id)
    if job is None or job.state != JobState.done:
        raise HTTPException(status_code=404, detail="Relatório não encontrado ou ainda não concluído")
    return job.result
