# 0002. Colocar o LiteLLM Proxy como AI Gateway entre a aplicação e os providers

- Status: aceita
- Data: 2026-09-26
- Nível: solução

## Contexto

Na v1, a aplicação depende do que é mais volátil no problema (diagnóstico, Dores 3 e 4):

- dois SDKs (`openai` e `anthropic`) com formatos de chamada e de resposta diferentes;
- nomes de modelo físicos, base URLs e chaves de provider em `config.py`;
- timeout e retry herdados dos padrões dos SDKs (600 s de leitura, 2 retries), contra os 30 s da borda;
- nenhum destino alternativo: quando um provider cai, a feature cai.

A ADR 0001 exige dois providers equivalentes, credenciais fora das aplicações e um teto de gasto aplicado na infraestrutura. O requisito 5 pede capacidades lógicas, troca de modelo sem tocar na aplicação, chaves com orçamento e limite, retry, timeout e fallback.

## Opções consideradas

1. Biblioteca na aplicação (ex.: o SDK `litellm` como dependência do `app`). Unifica o formato, mas as chaves continuam no ambiente da aplicação, e trocar modelo continua exigindo reiniciar a aplicação. Orçamento por chave não existe.
2. Adaptador próprio na aplicação, com retry e fallback escritos à mão. Mesmo problema de credencial e de troca, mais código de resiliência para manter.
3. Gateway self-hosted como serviço separado: LiteLLM Proxy.
4. Gateway SaaS. Proibido pelo desafio: o avaliador precisa subir tudo localmente.

## Decisão

Opção 3: o LiteLLM Proxy (`ghcr.io/berriai/litellm:v1.102.1`, a versão testada pelo README do provider), como serviço `gateway` no compose, com a configuração versionada em `gateway/`.

Posição: é o único caminho da aplicação até os modelos. A aplicação chama `http://gateway:4000/v1` no formato Chat Completions, com o nome lógico da capacidade no campo `model` e a chave virtual `helpdesk-app`. O gateway traduz para o formato nativo de cada provider (Chat Completions ou Messages).

Onde mora cada mecanismo:

| Mecanismo | Onde | Por quê |
|---|---|---|
| Nomes lógicos → modelo físico | gateway (`model_list`) | Troca de modelo sem tocar na aplicação (ADR 0003) |
| Chaves dos providers | gateway (`env_file: .env`) | Credencial fora da aplicação (ADR 0001) |
| Chaves virtuais, orçamento, limite de requisições | gateway + Postgres | ADR 0006 |
| Timeout por destino, retry com backoff, fallback técnico e com modelo fraco | gateway (`router_settings`) | Um lugar só; ADR 0005 |
| Teto de tempo da chamada inteira, retry do SDK desligado | aplicação (`adapters.gateway`) | Garante resposta antes dos 15 s e da borda, mesmo se o gateway travar |
| Evento `error` no meio do stream, falha rápida do relatório, estado das tarefas | aplicação | É contrato HTTP da feature, não infraestrutura (ADR 0004) |

## Consequências

- Melhor: a aplicação passa a falar um único formato, sem nenhum nome físico e sem chave de provider (o SDK `anthropic` saiu do `app`). Trocar modelo ou provider é editar `gateway/config.yaml` e reiniciar só o `gateway`.
- Pior: mais dois serviços para operar (`gateway` e o banco `gateway-db`, ADR 0006) e um salto de rede a mais: cerca de 0,2 a 0,5 s de overhead medido na primeira chamada. Enquanto o gateway reinicia (cerca de 16 s), as features de IA respondem `503`.
- Limitações encontradas no LiteLLM e como foram tratadas:
  - Não conhece o preço dos modelos simulados. Os preços do README do provider foram declarados por deployment (`input_cost_per_token`, `output_cost_per_token`); sem isso, nenhum orçamento estouraria.
  - Chaves virtuais só existem com banco e não podem ser declaradas no YAML. Um script (`gateway/provision.py`) cria as chaves na subida, sem passo manual.
  - A imagem não tem `curl`. O provisionamento e o healthcheck usam o Python da imagem.
  - O cooldown padrão tira do rodízio um destino que falhou, e aí as requisições seguintes nem tentam o primário. Foi desligado (`disable_cooldowns: true`) para que o comportamento de cada requisição seja o declarado no README e verificável no `/admin/calls`.
  - Retries em camadas se multiplicam (pista do desafio). O SDK na aplicação usa `max_retries=0`; só o gateway repete.

## Evidência

```
grep -rE "gpt-fake|claude-fake" app/                                  # vazio
grep -rE "FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY|sk-fake-openai|sk-ant-fake" app/   # vazio
docker compose exec app env | grep -i key                             # só GATEWAY_API_KEY
curl -s "localhost:8090/admin/calls?last=5"                           # chamadas chegam pelo gateway
```
