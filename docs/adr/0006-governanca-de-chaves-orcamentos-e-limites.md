# 0006. Governança por chaves virtuais do gateway, com orçamento e limite de requisições, guardadas em Postgres

- Status: aceita
- Data: 2026-09-26
- Nível: solução

## Contexto

- A ADR 0001 fixa um teto de US$ 100 a cada 30 dias para o helpdesk e tira as credenciais dos providers das aplicações.
- O requisito 5 pede pelo menos uma chave com orçamento e uma com limite de requisições, com recusa antes de chegar ao provider.
- Chaves virtuais, orçamentos e o gasto acumulado no LiteLLM só existem com um banco de dados. Sem banco, o proxy aceita apenas a master key, sem orçamento por chave.
- O LiteLLM não conhece o preço dos modelos simulados: sem declarar, calcula custo zero e nenhum orçamento estoura.
- As chaves precisam existir sem passo manual, porque o avaliador sobe tudo com um comando.

## Opções consideradas

1. Master key compartilhada, sem orçamento. Não atende o requisito.
2. Orçamento e rate limit na aplicação. As chaves dos providers voltariam a ser da aplicação, e cada aplicação reimplementaria o controle.
3. Chaves virtuais no gateway, persistidas num Postgres dedicado (`gateway-db`), criadas por script na subida.

## Decisão

Opção 3.

Chaves (declaradas em `gateway/keys.json`, valores em `.env`):

| Chave (alias) | Uso | Modelos | Orçamento | Limite |
|---|---|---|---|---|
| `helpdesk-app` (`GATEWAY_APP_KEY`) | A aplicação | Só as 4 capacidades primárias | US$ 100 / 30 dias (ADR 0001) | 600 req/min: a F3 dispara 34 chamadas em cerca de 30 s, mais o tráfego interativo |
| `governance-budget-demo` (`GATEWAY_BUDGET_DEMO_KEY`) | Roteiro de governança | `ticket-classification` | US$ 0,0001 | nenhum |
| `governance-rpm-demo` (`GATEWAY_RPM_DEMO_KEY`) | Roteiro de governança | `ticket-classification` | nenhum | 2 req/min |

- A master key (`LITELLM_MASTER_KEY`) é só de administração e fica no gateway. A aplicação recebe apenas `GATEWAY_API_KEY`, por variável explícita no compose, sem `env_file`.
- O orçamento da chave de demonstração é menor que o custo de uma classificação (cerca de US$ 0,00014): a primeira chamada passa e acumula gasto acima do limite, e as seguintes são recusadas. As chaves de demonstração existem para provar a recusa sem gastar o orçamento real da aplicação nem bloquear o helpdesk.
- Preços por token declarados em cada destino de `gateway/config.yaml`, copiados do README do provider.
- Provisionamento: `gateway/entrypoint.sh` sobe o LiteLLM e roda `gateway/provision.py`, que espera o `/health/readiness` e cria cada chave (`/key/generate`) ou a reaplica (`/key/update`, zerando o gasto). É idempotente. O healthcheck do serviço só passa depois do provisionamento, e o `app` só sobe com o `gateway` saudável.

**Serviço `gateway-db` (Postgres 16):** existe por causa do requisito 5 (governança mínima: chave com orçamento e chave com limite). O LiteLLM guarda nele as chaves virtuais, os orçamentos e o gasto por chave. Sem volume nomeado: um `docker compose down` apaga o gasto, e as chaves são recriadas na subida seguinte. Para o desafio isso basta. Em produção, o banco precisaria de volume persistente, senão o teto mensal zera a cada recriação.

## Consequências

- Melhor: o teto corporativo é aplicado num lugar só. Uma requisição fora do orçamento ou do limite é recusada pelo gateway com `429`, sem chegar ao provider e sem custar nada.
- Pior: um banco a mais para operar. O provisionamento zera o gasto a cada subida do gateway: aceitável aqui (a configuração versionada é a fonte da verdade), mas em produção o gasto do ciclo precisa sobreviver a um restart.
- A vigiar: o gasto da `helpdesk-app` perto do teto. Quando estourar, as quatro features passam a responder `503` (F2 e F4 também; a F3 chega a `failed`).

## Evidência

Roteiro de governança do README (automatizado em `tests/acceptance/test_governance.py`), com `/admin/reset` antes:

- `governance-budget-demo`: 1ª chamada `200`; 2ª e 3ª `429` com `"type": "budget_exceeded"` e a mensagem `Budget has been exceeded! ... Current cost: 0.0001425, Max budget: 0.0001`. `/admin/calls`: 1 chamada.
- `governance-rpm-demo`: 1ª e 2ª `200`; 3ª `429` `Rate limit exceeded ... Limit type: requests. Current limit: 2`. `/admin/calls`: 2 chamadas.
