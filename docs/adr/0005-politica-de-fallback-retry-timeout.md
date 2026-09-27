# 0005. Política de timeout, retry e fallback (técnico e com modelo fraco) por feature

- Status: aceita
- Data: 2026-09-26
- Nível: solução

## Contexto

- v1 (diagnóstico, Dor 3): com `error_500`, o SDK repetiu 3 vezes o mesmo destino fora do ar e a F1 devolveu `500`. Com `timeout`, a borda devolveu `504` em 32,8 s enquanto o SDK esperaria até 600 s por tentativa, com 2 retries. Nenhuma feature tinha destino alternativo.
- Os modelos `large` dos dois providers são equivalentes: mesma saída para a mesma entrada.
- Qualidade do `mini`, comparada no provider com as mesmas entradas (diagnóstico, "O modelo barato não é tão bom"):

| Tarefa | `mini` contra `large` |
|---|---|
| `classify` | Saída idêntica em 200 de 200 tickets |
| `topics` | Saída idêntica no lote de 150 tickets (e 4,6× mais rápida: 2,7 s contra 12,6 s) |
| `suggest` | Texto coerente e do mesmo tema, mas mais curto (1.099 contra 2.451 caracteres) |
| `extract` | `order_number` errado em 31 de 200 tickets (15,5%): pega o primeiro número de 6 dígitos, que pode ser a nota fiscal (TK-00002: `#530720` em vez de `#605065`). `product` nunca é encontrado (o `large` encontra em 37 de 200). |

## Opções consideradas

1. Retry no SDK da aplicação e nenhum fallback (a v1).
2. Retry e fallback na aplicação, escritos à mão.
3. Timeout por destino, retry limitado e fallbacks no gateway, com o modelo fraco decidido feature por feature. Na aplicação, só o teto de tempo da chamada inteira.
4. Fallback com modelo fraco ligado para todas as features ("uma resposta é sempre melhor que nenhuma").

## Decisão

Opção 3. Configuração em `gateway/config.yaml` (`router_settings`) e teto em `app/helpdesk/config.py`.

**Retry (gateway):** 1 retry, com backoff, só para falha transitória: `InternalServerErrorRetries: 1` e `RateLimitErrorRetries: 1`. No `429`, o LiteLLM respeita o `Retry-After`; no `500`, usa backoff exponencial (cerca de 0,8 s medido entre as tentativas). `TimeoutErrorRetries: 0`: um destino que acabou de travar tende a travar de novo, e repetir gastaria o orçamento de latência que o fallback precisa. Erros de requisição (`400`, `401`) não são repetidos. O SDK na aplicação usa `max_retries=0`: retries em duas camadas se multiplicariam.

**Número máximo de tentativas por destino** (declarado também no README): 2 no primário, 2 no fallback técnico e 2 no modelo fraco (1 + 1 retry) para `500` e `429`; 1 por destino em timeout. Pior caso: 6 chamadas ao provider por requisição.

**Timeout por destino (gateway) e teto da chamada (aplicação):**

| Capacidade | Timeout por destino no gateway | Pior caso no gateway | Teto na aplicação |
|---|---|---|---|
| `ticket-classification` | 4 s (normal: 1,1 s) | 4 + 4 + 4 = 12 s | 12 s → `503` |
| `order-extraction` | 4 s (normal: 1,1 s) | 4 + 4 = 8 s | 12 s |
| `reply-suggestion` | 3 s sem receber bytes do stream (`stream_timeout`; primeiro token em 0,8 s) | 3 + 3 + 3 = 9 s até o primeiro trecho | 12 s sem bytes |
| `topics-report` | 18 s large, 8 s mini (normal: 9 a 12,6 s large, 2,7 s mini) | 18 + 18 + 8 = 44 s | 50 s por lote → `failed` |

**Fallback técnico:** para toda capacidade, o `large` equivalente no outro provider (`-alt`). Como os `large` são equivalentes, esse fallback é transparente para o usuário. Cooldown desligado (`disable_cooldowns: true`): toda requisição tenta o primário primeiro, e o `/admin/calls` mostra sempre a mesma sequência.

**Fallback com modelo fraco, feature por feature.** A pergunta é "uma resposta pior é melhor que nenhuma resposta, para quem consome esta feature?":

| Feature | Sem nenhum `large` disponível | Evidência | Por quê |
|---|---|---|---|
| F1 Classificar | Responde com `gpt-fake-mini`: `200`, mesmo corpo | `classify` idêntico em 200/200 | Não há resposta pior: a saída é a mesma. Falhar travaria a abertura do ticket por nada. |
| F2 Sugerir | Responde com `claude-fake-mini`: stream `200`, texto mais curto | `suggest` do mini é coerente, com 1.099 caracteres | O atendente lê e edita antes de enviar: uma sugestão mais curta ainda economiza trabalho, e o erro humano é filtrado na revisão. Nenhuma sugestão é pior que uma sugestão curta. |
| F3 Relatório | Responde com `claude-fake-mini`: tarefa chega a `done`, relatório idêntico | `topics` idêntico no lote de 150 | Sem perda de qualidade, e mais rápido. |
| F4 Extrair | **Falha explícita**: `503` `{"detail": "Serviço de IA indisponível: ...", "capability": "order-extraction"}` | `extract` do mini erra o pedido em 15,5% e nunca acha o produto | A automação troca sem revisão humana. Um pedido errado gera uma troca errada (frete, estoque, cliente). Uma falha explícita deixa a automação reprocessar depois ou escalar para um humano; um dado errado ninguém vê. |

**Mid-stream (F2):** o LiteLLM só tenta fallback enquanto nenhum conteúdo foi gerado (código de `Router.stream_with_fallbacks`: se já há conteúdo, relança o erro original). Recomeçar a sugestão em outro modelo depois de o atendente ter lido um quarto dela duplicaria ou contradiria o texto. Depois do primeiro trecho, a falha chega ao cliente como `event: error`.

## Consequências

- Melhor: com o primário fora, toda feature responde com sucesso pelo outro provider. Com os dois `large` fora, três features seguem funcionando e a F4 falha de forma rápida e explícita. Nenhum cenário depende da borda para terminar.
- Pior: com o primário em `500`, a F1 leva cerca de 3,3 s em vez de 1,1 s (2 tentativas, backoff e fallback); com `429`, cerca de 7,2 s (o `Retry-After` é respeitado duas vezes). Os dois casos ficam dentro dos 15 s, mas acima dos 3 s do modo normal. Sem circuit breaker (fora de escopo), um primário fora do ar continua recebendo 2 tentativas por requisição.
- A vigiar: se a qualidade do `mini` mudar (nova versão), a tabela acima precisa ser refeita com a mesma comparação. Os timeouts dependem das velocidades declaradas dos modelos: um modelo mais lento exige rever os 4 s e os 18 s.

## Evidência

`/admin/calls` de cada cenário (também automatizado em `tests/acceptance/test_resilience.py`):

- F1 com `gpt-fake-large` em `error_500`: `gpt-fake-large 500`, `gpt-fake-large 500`, `claude-fake-large 200`. Mesmo padrão nas outras três capacidades, cada uma com seu primário.
- Dois `large` em `error_500`:
  - F1: 2× `gpt-fake-large 500`, 2× `claude-fake-large 500`, `gpt-fake-mini 200`, total de 5,2 s.
  - F2: 2× `claude-fake-large 500`, 2× `gpt-fake-large 500`, `claude-fake-mini 200` (stream), 6,1 s.
  - F3 (1 dia): mesma sequência, terminando em `claude-fake-mini 200`, tarefa `done`.
  - F4: 2× `gpt-fake-large 500`, 2× `claude-fake-large 500`, nenhuma chamada a `mini`, resposta `503` em 4,2 s.
- F1 com `gpt-fake-large` em `timeout`: `gpt-fake-large 504` (pendurada, sem retry) e `claude-fake-large 200` 4 s depois, `200` em 5,1 s. Com os dois providers inteiros em `timeout`: `503` em 12,0 s.
- F1 com `gpt-fake-large` em `error_429`: `429` às 02:11:20.6, `429` às 02:11:23.3 (`Retry-After: 2` respeitado), `claude-fake-large 200` às 02:11:25.9.
