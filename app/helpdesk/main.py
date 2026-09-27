from fastapi import FastAPI

from . import config, tickets
from .adapters.gateway import GatewayClient
from .classification import TicketClassifier
from .extraction import OrderExtractor
from .report import TopicsReporter
from .schemas import (Classification, OrderData, PeriodInput, ReplySuggestion, TicketInput,
                      TopicsReport)
from .suggestion import ReplySuggester

# Ponto de composição: o único lugar que conhece o adaptador concreto do gateway.
gateway = GatewayClient(config.GATEWAY_BASE_URL, config.GATEWAY_API_KEY, config.GATEWAY_TIMEOUT_S)
classifier = TicketClassifier(gateway, config.CLASSIFICATION_CAPABILITY)
suggester = ReplySuggester(gateway, config.SUGGESTION_CAPABILITY, config.MAX_OUTPUT_TOKENS)
extractor = OrderExtractor(gateway, config.EXTRACTION_CAPABILITY)
reporter = TopicsReporter(gateway, config.REPORT_CAPABILITY, tickets.in_period,
                          config.TICKETS_PER_CALL, config.MAX_OUTPUT_TOKENS)

app = FastAPI(title="Helpdesk")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tickets/classification")
def classify_ticket(ticket: TicketInput) -> Classification:
    return classifier.classify(ticket)


@app.post("/tickets/reply-suggestion")
def suggest_reply(ticket: TicketInput) -> ReplySuggestion:
    return suggester.suggest(ticket)


@app.post("/tickets/extraction")
def extract_order_data(ticket: TicketInput) -> OrderData:
    return extractor.extract(ticket)


@app.post("/reports/topics")
def topics_report(period: PeriodInput) -> TopicsReport:
    return reporter.topics(period)
