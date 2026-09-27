"""Casos fixados pela caracterização. Compartilhado entre os testes e o gravador."""

CONTRACT_TEXT = "Meu pedido #481516 não chegou e já passou do prazo, urgente"

# Um ticket por categoria/prioridade relevante.
CLASSIFICATION_TICKETS = ["TK-00002", "TK-00009", "TK-00012", "TK-00015", "TK-00023"]

# Nota fiscal + pedido, produto sem pedido, pedido sem "#", produto + pedido + nota, nada.
EXTRACTION_TICKETS = ["TK-00002", "TK-00007", "TK-00015", "TK-00036", "TK-00001"]

SUGGESTION_TICKET = "TK-00042"

# Dois dias somam mais de 150 tickets: exercita a agregação entre lotes.
REPORT_PERIOD = {"start": "2026-08-01", "end": "2026-08-02"}
EMPTY_PERIOD = {"start": "2026-09-01", "end": "2026-09-30"}
