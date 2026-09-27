import os

# O AI Gateway é o único caminho até os modelos. A aplicação conhece só o endereço dele,
# a própria chave e os nomes lógicos das capacidades; provider, modelo físico,
# credenciais dos providers, retries e fallbacks ficam em gateway/config.yaml.
GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://gateway:4000/v1")
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]

# Teto da aplicação por chamada ao gateway, com retries e fallbacks incluídos (ADR 0005).
# Interativo (F1, F2, F4): abaixo dos 15 s exigidos e dos 30 s da borda.
INTERACTIVE_TIMEOUT_S = 12
# Lote do relatório (F3): acima do pior caso do gateway (18 + 18 + 8 s) e abaixo dos 60 s
# em que uma tarefa sem saída precisa chegar a failed.
REPORT_CALL_TIMEOUT_S = 50

CLASSIFICATION_CAPABILITY = "ticket-classification"
SUGGESTION_CAPABILITY = "reply-suggestion"
REPORT_CAPABILITY = "topics-report"
EXTRACTION_CAPABILITY = "order-extraction"

MAX_OUTPUT_TOKENS = 2000

TICKETS_FILE = "/data/tickets.jsonl"
TICKETS_PER_CALL = 150
REPORT_CONCURRENCY = 12
REPORT_RETRY_AFTER_S = 5
