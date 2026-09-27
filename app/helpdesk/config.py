import os

# O AI Gateway é o único caminho até os modelos. A aplicação conhece só o endereço dele,
# a própria chave e os nomes lógicos das capacidades; provider, modelo físico e
# credenciais dos providers ficam em gateway/config.yaml.
GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://gateway:4000/v1")
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]
GATEWAY_TIMEOUT_S = 60

CLASSIFICATION_CAPABILITY = "ticket-classification"
SUGGESTION_CAPABILITY = "reply-suggestion"
REPORT_CAPABILITY = "topics-report"
EXTRACTION_CAPABILITY = "order-extraction"

MAX_OUTPUT_TOKENS = 2000

TICKETS_FILE = "/data/tickets.jsonl"
TICKETS_PER_CALL = 150
