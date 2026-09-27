# Helpdesk com IA: da integração frágil à arquitetura resiliente

> O enunciado do desafio está em [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Visão geral

O helpdesk tem quatro features de IA (classificar ticket, sugerir resposta, relatório de temas e extrair dados do pedido). Elas deixaram de chamar os SDKs dos providers e passaram a pedir **capacidades lógicas** (`ticket-classification`, `reply-suggestion`, `topics-report`, `order-extraction`) a um **AI Gateway self-hosted (LiteLLM Proxy)**. É o gateway que decide o modelo físico, guarda as chaves dos providers, aplica orçamento e limite de requisições por chave virtual e cuida da resiliência. Na aplicação, um único componente fala com o gateway (`adapters.gateway`), e as features dependem só de um port (`ports.CompletionGateway`). Cada feature é entregue no modo que o contrato dela pede: F1 e F4 síncronas com timeout explícito, F2 em streaming (SSE) e F3 como Asynchronous Request-Reply (`202` + polling), processando os lotes em paralelo.

Quando um provider cai, cada capacidade tenta o primário no máximo 2 vezes (1 retry com backoff, só em falha transitória; timeout vai direto para o próximo destino) e passa para o modelo `large` equivalente no outro provider, que dá a mesma resposta. O usuário não percebe nada além de alguns segundos a mais. Se os dois `large` caírem, classificação, sugestão e relatório respondem com o modelo `mini`, porque para eles uma resposta pior (ou igual) é melhor que nenhuma. A extração falha de forma explícita (`503`), porque alimenta uma automação sem revisão humana e o `mini` erra o número do pedido em 15,5% dos tickets. Nenhum cenário termina em `504` da borda.

## Diagnóstico da v1

Executado sobre a tag `v1-coupled` (a aplicação como foi recebida): `git checkout v1-coupled && cp .env.example .env && docker compose up -d --build --wait`, tudo medido pela borda (`localhost:8000`). Antes de cada cenário, `curl -s -X POST localhost:8090/admin/reset`.

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

Pré-requisitos: Docker com Compose v2 e Python 3.12 (para testes e métrica).

```
cp .env.example .env
docker compose up -d --build --wait
curl -s localhost:8000/health
```

O compose sobe `provider-fake`, `gateway-db` (Postgres do gateway), `gateway` (LiteLLM, que provisiona as chaves virtuais sozinho), `app` e `edge`. A primeira subida baixa as imagens; depois disso, o `--wait` leva cerca de 30 s. O gateway também fica exposto em `localhost:4000`, para o roteiro de governança.

Ambiente de testes e métrica (uma vez):

```
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt -r metrics/requirements.txt
```

Testes de caracterização (com o compose no ar, cerca de 45 s):

```
.venv/bin/pytest tests/characterization -q
```

Critérios de aceite da `main` (fluxos, fallback, timeouts, governança; provocam falhas no provider simulado e o devolvem ao modo normal no fim; cerca de 2,5 min):

```
.venv/bin/pytest tests/acceptance -q
```

Métrica de acoplamento: o script recebe a pasta `app/helpdesk` de qualquer checkout e grava `metrics/results/<nome>.csv` e `metrics/results/<nome>.png`:

```
.venv/bin/python metrics/coupling.py app/helpdesk --name main

git worktree add ../v1 v1-coupled
.venv/bin/python metrics/coupling.py ../v1/app/helpdesk --name v1-coupled
git worktree add ../v2 v2-decoupled
.venv/bin/python metrics/coupling.py ../v2/app/helpdesk --name v2-decoupled
```

## Métrica

| v1-coupled | v2-decoupled | main |
|---|---|---|
| ![v1](metrics/results/v1-coupled.png) | ![v2](metrics/results/v2-decoupled.png) | ![main](metrics/results/main.png) |

CSVs: [v1-coupled](metrics/results/v1-coupled.csv), [v2-decoupled](metrics/results/v2-decoupled.csv), [main](metrics/results/main.csv). A leitura completa está na [ADR 0007](docs/adr/0007-leitura-da-metrica-de-acoplamento.md).

- **v1-coupled**: três componentes na zona de dor. O problema real é `llm` (Ca = 4, D = 0,80): as quatro features dependem de um módulo concreto com os dois SDKs, cada um com seu formato. Junto vem `config` (Ca = 6, D = 1,00), com nomes físicos, URLs e chaves de provider, o que mais muda. As features ficam perto da Main Sequence (I = 0,75), mas só porque importam esses dois concretos.
- **v2-decoupled**: `llm` sai do gráfico. Em seu lugar entra `ports` (A = 1, I = 0), exatamente sobre a Main Sequence, e as features passam a depender dele (I = 0,67, D = 0,33). O D das features subiu um pouco porque elas trocaram dois concretos por um abstrato, que é a direção certa das setas. `adapters.gateway` fica em I = 0,50, fora da zona, depois da Revisão 1 do [plano](docs/refactoring-plan.md). `config` perde 4 dependentes (Ca de 6 para 2).
- **main**: `ports` ganha o port `JobStore` e o erro `CapabilityUnavailable` e desce para A = 0,67, I = 0,13, D = 0,21, ainda perto da sequência. O novo `adapters.job_store` (estado das tarefas da F3) fica junto das features. `main` é o único componente que importa os adaptadores.
- **Exceções declaradas (estáveis por natureza)**: `schemas` (tipos de valor do contrato, que só mudam com o contrato) e `config` (sem nada de provider desde a v2; só endereço e chave do gateway, nomes lógicos e parâmetros). A justificativa está na ADR 0007. O componente que chama o gateway e as features estão fora da zona.
- **Componente que chama o gateway**: `adapters.gateway` ([app/helpdesk/adapters/gateway.py](app/helpdesk/adapters/gateway.py)). Nenhuma feature o importa. Só o ponto de composição ([app/helpdesk/main.py](app/helpdesk/main.py)) depende dele.

## Tabela de capacidades

Configuração em [gateway/config.yaml](gateway/config.yaml). Tentativas contadas como chamadas ao provider, visíveis no `/admin/calls`.

| Capacidade lógica | Feature | Modelo primário | Fallback técnico | Política com modelo fraco | Máx. de tentativas por destino |
|---|---|---|---|---|---|
| `ticket-classification` | F1 Classificar | `openai/gpt-fake-large` (timeout 4 s) | `anthropic/claude-fake-large` (4 s) | Aceita: `openai/gpt-fake-mini` (4 s) | primário 2, fallback técnico 2, fraco 2 |
| `reply-suggestion` | F2 Sugerir | `anthropic/claude-fake-large` (3 s sem bytes no stream) | `openai/gpt-fake-large` (3 s) | Aceita: `anthropic/claude-fake-mini` (3 s) | primário 2, fallback técnico 2, fraco 2 |
| `topics-report` | F3 Relatório | `anthropic/claude-fake-large` (18 s) | `openai/gpt-fake-large` (18 s) | Aceita: `anthropic/claude-fake-mini` (8 s) | primário 2, fallback técnico 2, fraco 2 |
| `order-extraction` | F4 Extrair | `openai/gpt-fake-large` (4 s) | `anthropic/claude-fake-large` (4 s) | Recusa: falha explícita | primário 2, fallback técnico 2 |

- As 2 tentativas por destino valem para falha transitória (`500`, `429`): 1 chamada mais 1 retry com backoff (exponencial no `500`; no `429`, respeitando o `Retry-After`). Em timeout, é 1 tentativa por destino: sem retry, direto para o próximo.
- O SDK na aplicação não repete (`max_retries=0`). A aplicação põe um teto na chamada inteira, com os fallbacks incluídos: 12 s para F1, F2 e F4, e 50 s por lote da F3 ([ADR 0005](docs/adr/0005-politica-de-fallback-retry-timeout.md)).

## Tabela de fallback

O que acontece quando nenhum modelo `large` está disponível (ex.: `gpt-fake-large` e `claude-fake-large` em `error_500`):

| Feature | Resposta | Status | Evidência que sustenta |
|---|---|---|---|
| F1 Classificar | Classificação pelo `gpt-fake-mini`, mesmo corpo do `large` | `200` (≈ 5,2 s) | `classify` do mini é idêntico em 200/200 tickets |
| F2 Sugerir | Stream da sugestão pelo `claude-fake-mini` (mais curta), terminando em `event: end` | `200` `text/event-stream` | Texto coerente com ≈ 1.100 caracteres; o atendente revisa antes de enviar |
| F3 Relatório | Tarefa chega a `done`, relatório pelo `claude-fake-mini`, idêntico ao do `large` | `202`, depois `303` e `200` | `topics` do mini é idêntico |
| F4 Extrair | Falha explícita, sem chamar o mini: `{"detail": "Serviço de IA indisponível: o gateway recusou ou falhou (HTTP 500)", "capability": "order-extraction"}` | `503` (≈ 4,2 s) | O mini erra o pedido em 15,5% e nunca acha o produto; a automação troca sem revisão |

Com os dois providers inteiros fora: F1, F2 (antes do primeiro trecho) e F4 respondem `503` com o mesmo formato; a F3 chega a `failed` com `reason` (≈ 7 s com `error_500`, ≈ 44 s com `timeout`). Detalhes na [ADR 0005](docs/adr/0005-politica-de-fallback-retry-timeout.md).

## Fluxos

Decisões e justificativas na [ADR 0004](docs/adr/0004-modo-de-execucao-por-feature.md). Tudo pela borda, `localhost:8000`.

**F1 Classificar: síncrono** (≈ 1,1 s; `503` explícito em até 12 s se nenhum modelo responder)

```
curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}'
# 200 {"ticket_id":"TK-00042","category":"delivery","priority":"high"}
```

**F2 Sugerir: streaming SSE** (primeiro trecho em ≈ 0,8 s, texto completo em ≈ 16 s)

```
curl -N -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}'
# 200 Content-Type: text/event-stream
# data: {"chunk": "Olá!"}
# data: {"chunk": " Sin"}
# ...
# event: end
# data: {"ticket_id": "TK-00042"}
```

A sugestão completa é a concatenação dos `chunk`. Se a geração cair depois do primeiro trecho, o stream termina com `event: error` / `data: {"ticket_id": "TK-00042", "message": "A geração foi interrompida"}`. Se nenhum modelo atender antes do primeiro trecho, a resposta é `503` JSON (sem stream).

**F3 Relatório: Asynchronous Request-Reply** (aceite em ≈ 20 ms, mês pronto em ≈ 30 s)

```
curl -si -X POST localhost:8000/reports/topics -H "Content-Type: application/json" \
  -d '{"start": "2026-08-01", "end": "2026-08-31"}'
# 202 Accepted
# location: /reports/topics/status/3dda3dba011f
# retry-after: 5
# {"id":"3dda3dba011f","state":"pending"}

curl -si localhost:8000/reports/topics/status/3dda3dba011f
# 200 {"state":"running","progress":"1800/5000"}      (repita após Retry-After)
# 200 {"state":"failed","reason":"Modelo indisponível para o relatório: ..."}   (se falhar)
# 303 See Other, location: /reports/topics/3dda3dba011f                          (quando done)

curl -s localhost:8000/reports/topics/3dda3dba011f
# 200 {"start":"2026-08-01","end":"2026-08-31","total_tickets":5000,"topics":[...]}

# ou, seguindo o redirect de uma vez quando estiver pronto:
curl -sL localhost:8000/reports/topics/status/3dda3dba011f
```

Campo adicional em relação aos Contratos sugeridos: o corpo do `202` traz `{"id", "state"}`. IDs desconhecidos respondem `404`, e o resultado de uma tarefa ainda não concluída também responde `404`. `start` > `end` continua respondendo `422` no próprio `POST`.

**F4 Extrair: síncrono** (≈ 1,2 s; `503` explícito se não houver modelo `large`)

```
curl -s -X POST localhost:8000/tickets/extraction -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00002", "text": "Tenho aqui a nota fiscal 530720. O produto veio quebrado na caixa, pedido #605065."}'
# 200 {"ticket_id":"TK-00002","order_number":"#605065","product":null}
```

Para provocar os cenários de falha: `curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" -d '{"provider": "openai", "model": "gpt-fake-large", "mode": "error_500"}'`, conferir em `curl -s "localhost:8090/admin/calls?last=10"` e voltar ao normal com `curl -s -X POST localhost:8090/admin/reset`.

## Troca de modelo

Arquivo: [gateway/config.yaml](gateway/config.yaml). Em `model_list`, cada capacidade aponta para um destino físico declarado no topo do arquivo (`*openai-large`, `*openai-mini`, `*anthropic-large`, `*anthropic-mini`, cada um com provider, base URL, chave e preço).

Exemplo: passar a classificação para o modelo barato da OpenAI.

1. Em `gateway/config.yaml`, no item `model_name: ticket-classification`, troque `*openai-large` por `*openai-mini`:

   ```yaml
     - model_name: ticket-classification
       litellm_params: {<<: *openai-mini, timeout: 4}
   ```

2. Reinicie só o gateway (fica saudável em cerca de 15 s; a aplicação não é reconstruída nem reiniciada):

   ```
   docker compose restart gateway
   until [ "$(docker inspect -f '{{.State.Health.Status}}' $(docker compose ps -q gateway))" = healthy ]; do sleep 1; done
   ```

3. Confira:

   ```
   curl -s -X POST localhost:8090/admin/reset
   curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
     -d '{"ticket_id": "TK-1", "text": "Meu pedido não chegou"}'
   curl -s "localhost:8090/admin/calls?last=1"            # "model": "gpt-fake-mini"
   docker inspect -f '{{.State.StartedAt}}' $(docker compose ps -q app)   # inalterado
   ```

Trocar de provider é igual: `*anthropic-large` no lugar de `*openai-large`. Durante o restart do gateway, as features de IA respondem `503`. Para desfazer, volte a linha e repita o passo 2.

## Roteiro de governança

As chaves de demonstração são criadas automaticamente na subida ([gateway/keys.json](gateway/keys.json)): `governance-budget-demo` com orçamento de US$ 0,0001 e `governance-rpm-demo` com 2 requisições por minuto. A chave da aplicação (`helpdesk-app`) tem orçamento de US$ 100 a cada 30 dias e 600 req/min ([ADR 0006](docs/adr/0006-governanca-de-chaves-orcamentos-e-limites.md)).

```
REQ='{"model": "ticket-classification", "messages": [{"role": "user", "content": "TASK: classify\nMeu pedido não chegou"}]}'
curl -s -X POST localhost:8090/admin/reset > /dev/null
# (só se o roteiro já rodou antes: zera o gasto da chave de orçamento)
curl -s localhost:4000/key/update -H "Authorization: Bearer sk-gateway-master-0001" \
  -H "Content-Type: application/json" -d '{"key": "sk-governance-budget-0001", "spend": 0}' > /dev/null

# 1) Orçamento: a 1ª passa e gasta ~US$ 0,00014 (acima do orçamento); a 2ª é recusada
for i in 1 2; do curl -s -w "\n  -> HTTP %{http_code}\n" localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-governance-budget-0001" -H "Content-Type: application/json" -d "$REQ" | cut -c1-160; done
# {"id":"chatcmpl-...","model":"ticket-classification",...
#   -> HTTP 200
# {"error":{"message":"Budget has been exceeded! Key=governance-budget-demo (sk-...0001) Current cost: 0.00014..., Max budget: 0.0001","type":"budget_exceeded",...
#   -> HTTP 429

# 2) Limite de requisições: 2 por minuto; a 3ª é recusada
for i in 1 2 3; do curl -s -w "\n  -> HTTP %{http_code}\n" localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-governance-rpm-0001" -H "Content-Type: application/json" -d "$REQ" | cut -c1-160; done
#   -> HTTP 200
#   -> HTTP 200
# {"error":{"message":"Rate limit exceeded for api_key: ... Limit type: requests. Current limit: 2, ...
#   -> HTTP 429

# 3) As recusadas não chegaram ao provider: 5 requisições, 3 chamadas
curl -s "localhost:8090/admin/calls?last=50" | python3 -c "import json,sys; print(len(json.load(sys.stdin)), 'chamadas')"
# 3 chamadas
```

(Se o passo 2 for repetido dentro do mesmo minuto, a janela ainda está cheia e as 3 são recusadas: o número de chamadas em `/admin/calls` continua igual ao de respostas `200`.)

## Mapa de decisões

| ADR | Nível | Resumo |
|---|---|---|
| [0001](docs/adr/0001-politica-de-providers-e-teto-de-gasto.md) | corporativa | OpenAI e Anthropic homologados, com destino equivalente nos dois para toda capacidade; credenciais só na plataforma; teto de US$ 100 a cada 30 dias para o helpdesk |
| [0002](docs/adr/0002-ai-gateway-litellm.md) | solução | LiteLLM Proxy self-hosted como único caminho até os modelos; o que mora no gateway e o que mora na aplicação; limitações contornadas |
| [0003](docs/adr/0003-capacidades-logicas.md) | solução | Um nome lógico por feature, com grupos `-alt` e `-weak` internos; troca de modelo é uma linha no gateway |
| [0004](docs/adr/0004-modo-de-execucao-por-feature.md) | solução | F1 e F4 síncronas com timeout, F2 em streaming SSE, F3 em Asynchronous Request-Reply com lotes em paralelo |
| [0005](docs/adr/0005-politica-de-fallback-retry-timeout.md) | solução | Timeout por destino, 1 retry com backoff só em falha transitória, fallback técnico para o outro provider sempre, modelo fraco em F1/F2/F3 e falha explícita na F4 |
| [0006](docs/adr/0006-governanca-de-chaves-orcamentos-e-limites.md) | solução | Chaves virtuais com orçamento e rpm, provisionadas na subida; preços declarados; Postgres (`gateway-db`) justificado pelo requisito de governança |
| [0007](docs/adr/0007-leitura-da-metrica-de-acoplamento.md) | software | Leitura da Main Sequence nas três versões; `schemas` e `config` declarados estáveis por natureza |
| [0008](docs/adr/0008-features-dependem-de-port-adaptador-unico.md) | software | Features dependem de `ports.CompletionGateway`; `adapters.gateway` é o único componente que chama o gateway; `main` compõe |

Plano, piloto, revisões e handoff da refatoração: [docs/refactoring-plan.md](docs/refactoring-plan.md).
