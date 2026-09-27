# Helpdesk com IA: da integração frágil à arquitetura resiliente

> O enunciado do desafio está em [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Diagnóstico da v1

Ambiente: `cp .env.example .env && docker compose up -d --build --wait`, tudo medido pela borda (`localhost:8000`). Antes de cada cenário, `curl -s -X POST localhost:8090/admin/reset`.

Linha de base no modo normal (mesmo ticket TK-00002):

| Feature | Status | Tempo total | `/admin/calls` |
|---|---|---|---|
| F1 classificação | 200 | 1,23 s | 1 chamada `openai/gpt-fake-large`, 1.126 ms |
| F4 extração | 200 | 1,18 s | 1 chamada `openai/gpt-fake-large`, 1.076 ms |
| F2 sugestão | 200 | 17,6 s (primeiro byte também em 17,6 s) | 1 chamada `anthropic/claude-fake-large`, 613 tokens de saída, 16.127 ms |
| F3 relatório de 1 dia | 200 | 10,7 s | 1 lote de 137 tickets, 6.132 tokens de entrada, 9.801 ms |

### Dor 1: o relatório do mês não chega (e continua sendo pago)

```
curl -s -w "\nstatus=%{http_code} total=%{time_total}s\n" -X POST localhost:8000/reports/topics \
  -H "Content-Type: application/json" -d '{"start":"2026-08-01","end":"2026-08-31"}'
curl -s "localhost:8090/admin/calls?last=100"     # repetido pelos minutos seguintes
```

Observado:

- A borda responde `504 Gateway Time-out` em 32,8 s. O cliente não recebe nada.
- Depois do `504`, a aplicação continua: o `/admin/calls` mostra 4 chamadas `topics` no momento do `504`, 10 um minuto depois e 34 no final. A última termina às 01:36:55, 5 min 20 s depois de a borda ter desistido.
- As 34 chamadas somam 222.114 tokens de entrada e 12.162 de saída em `claude-fake-large`: US$ 0,85 pagos por um relatório que ninguém recebeu. Cada pedido repetido paga de novo.

Causa em `app/`:

- [app/helpdesk/report.py](app/helpdesk/report.py) processa os 34 lotes de 150 tickets (`config.TICKETS_PER_CALL`) em série dentro da requisição HTTP. Cada lote leva de 9 a 10 s, então o mês leva cerca de 6 min, contra os 30 s de `proxy_read_timeout` do [edge/nginx.conf](edge/nginx.conf). Em cadeia de proxies, o timeout mais curto vence.
- [app/helpdesk/main.py](app/helpdesk/main.py) declara as rotas com `def` síncrono: o FastAPI roda o handler numa thread do pool, e o fechamento da conexão pela borda não interrompe essa thread. Desistir não é cancelar.

### Dor 2: a sugestão deixa o atendente olhando uma tela parada

```
curl -s -o /dev/null -w "status=%{http_code} ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
  -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00002", "text": "O produto veio quebrado na caixa, pedido #605065."}'
```

Observado: `status=200 ttfb=17.62s total=17.62s`. O primeiro byte chega junto com o último. O `/admin/calls` mostra `stream: false` e 613 tokens de saída a 40 tokens/s: o provider leva 0,8 s para o primeiro token, e a aplicação espera os outros 15 s antes de mandar qualquer coisa. Está a 12 s de um `504` da borda.

Causa em `app/`: [app/helpdesk/llm.py](app/helpdesk/llm.py) (`call_anthropic`) chama `messages.create` sem `stream=True` e devolve só `response.content[0].text`; [app/helpdesk/suggestion.py](app/helpdesk/suggestion.py) monta um `ReplySuggestion` com o texto inteiro.

### Dor 3: com um provider fora do ar ou travado, parte do helpdesk para

```
curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" \
  -d '{"provider":"openai","mode":"error_500"}'
curl -s -w "\nstatus=%{http_code} total=%{time_total}s\n" -X POST localhost:8000/tickets/classification \
  -H "Content-Type: application/json" -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou, urgente"}'

curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" \
  -d '{"provider":"openai","mode":"timeout"}'
curl -s -w "\nstatus=%{http_code} total=%{time_total}s\n" -X POST localhost:8000/tickets/extraction \
  -H "Content-Type: application/json" -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou, urgente"}'
```

Observado:

- `error_500`: F1 responde `500 Internal Server Error` (texto puro) em 1,3 s. O `/admin/calls` mostra 3 chamadas a `gpt-fake-large` (01:32:52.864, 53.301, 54.079): o SDK repetiu 2 vezes, com backoff, o mesmo destino que estava fora. A Anthropic estava saudável e não foi tentada.
- `timeout`: F4 recebe `504` da borda em 32,8 s. No `/admin/calls` há uma chamada `gpt-fake-large` com `duration_ms: null`, ainda pendurada. O SDK espera até 600 s por tentativa e repete 2 vezes: a thread da aplicação pode ficar presa por até 15 min.
- Ao mesmo tempo, F2 (Anthropic) responde 200: metade do helpdesk (F1 e F4) para, a outra metade não.

Causa em `app/`:

- [app/helpdesk/llm.py](app/helpdesk/llm.py) cria `OpenAI(...)` e `Anthropic(...)` sem `timeout` nem `max_retries`. Valem os padrões dos SDKs, confirmados no container com `docker compose exec app python -c "..."`: `openai 3.19.0 Timeout(connect=5.0, read=600) max_retries=2` e `anthropic 1.8.0 Timeout(connect=5.0, read=600) max_retries=2`. São 600 s contra os 30 s da borda.
- [app/helpdesk/classification.py](app/helpdesk/classification.py) e [app/helpdesk/extraction.py](app/helpdesk/extraction.py) chamam `llm.call_openai` direto: cada feature está presa a um único provider, sem destino alternativo.

### Dor 4: trocar o modelo de uma feature exige mudar código e reconstruir

Demonstração temporária (desfeita antes da tag `v1-coupled`):

```
sed -i 's/CLASSIFICATION_MODEL = "gpt-fake-large"/CLASSIFICATION_MODEL = "gpt-fake-mini"/' app/helpdesk/config.py
docker compose up -d --build --wait app
curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou, urgente"}'
curl -s "localhost:8090/admin/calls?last=1"
git checkout app/helpdesk/config.py && docker compose up -d --build --wait app
```

Observado: foi preciso alterar código, reconstruir a imagem e recriar o container (`StartedAt` do `app` mudou de 01:30:09 para 01:37:21, 8 s de rebuild e restart, com as requisições em andamento perdidas). Só então o `/admin/calls` passou a mostrar `openai/gpt-fake-mini`. A troca de provider seria pior: F1 teria que passar de `call_openai` para `call_anthropic`, que tem outra assinatura de chamada e outro formato de resposta.

Causa em `app/`: [app/helpdesk/config.py](app/helpdesk/config.py) fixa os nomes físicos (`gpt-fake-large`, `claude-fake-large`), as base URLs e as chaves dos providers no código. Cada feature escolhe o provider pelo nome da função que importa de [app/helpdesk/llm.py](app/helpdesk/llm.py).

### O modelo barato não é tão bom (evidência para o fallback)

Mesmas entradas, direto no provider, `gpt-fake-large` contra `gpt-fake-mini`:

| Tarefa | Resultado |
|---|---|
| `classify` (200 tickets) | Saída idêntica em 200 de 200 |
| `topics` (lote de 150 tickets) | Saída idêntica; 2,7 s no mini contra 12,6 s no large |
| `suggest` | Texto coerente e do mesmo tema, mas mais curto: 1.099 contra 2.451 caracteres |
| `extract` (200 tickets) | `order_number` errado em 31 de 200 (15,5%): o mini pega o primeiro número de 6 dígitos, que pode ser a nota fiscal (TK-00002: `#530720` em vez de `#605065`). `product` nunca é encontrado (o large encontra em 37 de 200) |

## Como rodar

```
cp .env.example .env
docker compose up -d --build --wait
curl -s localhost:8000/health
```

Testes de caracterização (com o compose no ar):

```
python3 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt
.venv/bin/pytest tests/characterization -q
```
