# 0008. As features dependem de um port, e um único adaptador chama o gateway

- Status: aceita
- Data: 2026-09-26
- Nível: software

## Contexto

Na v1, cada feature importava `llm` e `config` e escolhia provider e modelo pelo nome da função (`call_openai` ou `call_anthropic`) e pela constante de configuração. Mudar de provider era mudar a feature (Dor 4). Com o gateway (ADR 0002), a aplicação fala um único formato, mas ainda é preciso decidir onde fica o código que o chama e como as features chegam até ele.

## Opções consideradas

1. Cada feature instancia o seu cliente do SDK apontando para o gateway.
2. Um módulo utilitário com funções (`call_gateway(...)`) importado pelas features, repetindo o formato da v1 com outro destino.
3. Um port (`ports.CompletionGateway`, um `typing.Protocol`) que expressa a capacidade de que as features precisam, um único adaptador concreto (`adapters.gateway.GatewayClient`) e composição no `main`.

## Decisão

Opção 3.

- `ports.CompletionGateway`: `complete(capability, prompt, max_tokens)` e `stream(capability, prompt, max_tokens)`. As falhas chegam como `ports.CapabilityUnavailable`, inclusive no meio de um stream. O port não menciona provider, modelo, formato nem credencial.
- `adapters.gateway.GatewayClient` é o único componente de `app/` que usa o SDK `openai` e chama o gateway. Ele herda explicitamente do port, com timeout explícito e `max_retries=0` (ADR 0005), e traduz `openai.APIError` para `CapabilityUnavailable`. Registra em log qual modelo físico atendeu (`served_by`), a partir do campo `model` da resposta.
- As features (`TicketClassifier`, `ReplySuggester`, `OrderExtractor`, `TopicsReporter`) recebem no construtor o gateway, o nome lógico da sua capacidade e o que mais precisarem (ex.: a leitura de tickets, o `JobStore`). Cada feature monta o próprio prompt (`TASK: ...`); o adaptador só transporta.
- `main` é o ponto de composição e o único importador dos adaptadores concretos. Ele monta dois clientes com tetos diferentes (interativo, 12 s; lote do relatório, 50 s) e os injeta. O mesmo vale para `adapters.job_store.InMemoryJobStore` atrás do port `JobStore` (ADR 0004).

## Consequências

- Melhor: trocar a forma de falar com os modelos (outro gateway, outro SDK, um dublê em teste) muda um adaptador e uma linha do `main`, e nenhuma feature. As features não conhecem HTTP de IA, SDK nem configuração.
- Pior: mais indireção (classe, port e composição) para quatro chamadas. O construtor de cada feature passa a listar dependências explícitas.
- A vigiar: nenhuma feature pode importar `adapters.*`. A régua da métrica e o `grep` do README verificam isso.

## Evidência

```
grep -rnE "from \.+adapters|import .*adapters" app/helpdesk
# app/helpdesk/main.py: from .adapters.gateway import GatewayClient
# app/helpdesk/main.py: from .adapters.job_store import InMemoryJobStore
grep -rln "openai" app/helpdesk      # só adapters/gateway.py
```
