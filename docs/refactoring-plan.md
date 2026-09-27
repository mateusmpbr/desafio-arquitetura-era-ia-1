# Plano de refatoração: v1-coupled → v2-decoupled

## Ponto de partida (medido)

Medição da `v1-coupled` com `metrics/coupling.py` ([CSV](../metrics/results/v1-coupled.csv), [gráfico](../metrics/results/v1-coupled.png)):

| Componente | Ca | Ce | I | A | D | Leitura |
|---|---|---|---|---|---|---|
| `config` | 6 | 0 | 0,00 | 0,00 | 1,00 | Zona de dor. Seis módulos dependem de nomes de modelo, URLs e chaves de provider. É exatamente o que muda com frequência. |
| `llm` | 4 | 1 | 0,20 | 0,00 | 0,80 | Zona de dor. As quatro features dependem de um módulo concreto com os dois SDKs, duas funções com assinaturas diferentes e nenhum contrato. |
| `schemas` | 5 | 0 | 0,00 | 0,00 | 1,00 | Zona de dor pela fórmula. São tipos de valor do contrato HTTP, que não mudam sem mudar o contrato. |
| `tickets` | 1 | 1 | 0,50 | 0,00 | 0,50 | Na fronteira, fora da zona. |
| `classification`, `extraction`, `suggestion` | 1 | 3 | 0,75 | 0,00 | 0,25 | Perto da Main Sequence, mas cada uma escolhe provider e modelo (`llm.call_openai(config.X_MODEL, ...)`). |
| `report` | 1 | 4 | 0,80 | 0,00 | 0,20 | Idem, e ainda orquestra os lotes. |
| `main` | 0 | 5 | 1,00 | 0,00 | 0,00 | Ponto de composição. |

O problema não é "D alto em geral". São dois componentes estáveis e concretos (`config` e `llm`) no caminho de toda feature, carregando justamente as decisões voláteis: provider, modelo, formato de API e credencial.

## Componentes-alvo e estratégia

| Alvo | Estratégia | Resultado esperado |
|---|---|---|
| `llm` | Inverter a dependência. Criar `ports` com um `Protocol` (`CompletionGateway`) que expressa a capacidade que a feature precisa ("complete esta tarefa nesta capacidade"). A implementação concreta vai para `adapters.gateway`, que fala só com o AI Gateway, usando um único formato (Chat Completions) e uma chave do gateway. `llm` deixa de existir. | `ports`: A = 1, I = 0 (D = 0). `adapters.gateway`: instável (I alto), importado só por `main`. |
| `config` | Reduzir Ca. Tirar dele tudo o que é do provider (chaves, base URLs, nomes físicos), que vai para a configuração do gateway. Sobram o endereço e a chave do gateway, os nomes lógicos das capacidades e os parâmetros do relatório, lidos do ambiente. Só o ponto de composição e os adaptadores de infraestrutura leem `config`; as features recebem o que precisam por construtor. | Ca de 6 para 2 ou 3. |
| Features (`classification`, `suggestion`, `extraction`, `report`) | Compor em vez de importar. Cada feature vira uma classe que recebe o `CompletionGateway` e o nome lógico da sua capacidade no construtor. Não importam `config` nem o adaptador. | Ce = `ports` + `schemas` (+ o que for do domínio). Nenhuma feature importa `adapters.gateway`. |
| `main` | Virar o ponto de composição: monta o adaptador com a configuração e injeta nas features. | Único importador de `adapters.gateway`. |
| `schemas` | Nenhuma. Tipos de valor do contrato HTTP, estáveis por natureza (declarados no ADR da métrica). | Continua em (0, 0). |

Critério de pronto (métrica, medido pela régua do requisito 3):

1. Nenhum componente na zona de dor (A < 0,5, I < 0,5 e D ≥ 0,5), exceto os declarados no ADR da métrica como estáveis por natureza. `adapters.gateway` e as features não podem ser exceção.
2. O código que chama o gateway fica num único componente (`adapters.gateway`), e o único componente que o importa é `main`.
3. `grep -rE "gpt-fake|claude-fake|FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY" app/` vazio.
4. Suíte de caracterização passando sem alteração (`git diff v1-coupled -- tests/characterization/` vazio).

## Piloto

Componente: `classification`, a feature mais simples e a que mais sofre com a troca de provider (a Dor 3 foi reproduzida nela).

O que foi feito: criado `ports.CompletionGateway` (`complete(capability, prompt, max_tokens)`), criado `adapters.gateway.GatewayClient` (SDK `openai` apontando para o LiteLLM, `max_retries=0`, timeout explícito), `classification` virou `TicketClassifier(gateway, capability)` e `main` passou a montar os dois. As outras três features continuaram em `llm`, ainda direto nos providers.

Medição antes e depois (mesmo script, mesma régua):

| Componente | Antes (v1) Ca/Ce/I/A/D | Depois do piloto Ca/Ce/I/A/D |
|---|---|---|
| `classification` | 1 / 3 / 0,75 / 0,00 / 0,25 | 1 / 2 / 0,67 / 0,00 / 0,33 |
| `llm` | 4 / 1 / 0,20 / 0,00 / 0,80 | 3 / 1 / 0,25 / 0,00 / 0,75 |
| `ports` (novo) | n/a | 1 / 0 / 0,00 / 1,00 / 0,00 |
| `adapters.gateway` (novo) | n/a | 1 / 0 / 0,00 / 0,00 / **1,00 (zona de dor)** |
| `adapters.gateway` depois da revisão 1 | n/a | 1 / 1 / 0,50 / 0,00 / 0,50 |

Testes: os 21 da caracterização passaram. `/admin/calls` mostrou `classify` em `openai/gpt-fake-large`, agora chegando pelo gateway.

O `D` da `classification` subiu de 0,25 para 0,33, e está certo que suba: ela deixou de depender de dois concretos (`config`, `llm`) e passou a depender de um abstrato (`ports`). A métrica de um componente sozinho não diz se ele melhorou. O que importa é para onde apontam as setas. O ganho que se mede está em `llm`, que perdeu um dependente, e em `ports`, que nasceu sobre a Main Sequence.

## Revisões do plano

**Revisão 1: o adaptador declara o port que implementa.** O plano previa `adapters.gateway` "instável (I alto)". O piloto desmentiu: implementado só por tipagem estrutural, o adaptador não importa nada do projeto (Ce = 0), e com `main` como único dependente ficou em I = 0, A = 0, D = 1, ou seja, dentro da zona de dor. É o componente que a regra proíbe como exceção, e com razão: um concreto do qual os outros dependem sem que ele dependa de nenhum contrato. A correção é a inversão de dependência de verdade. O adaptador herda explicitamente de `CompletionGateway` (`class GatewayClient(CompletionGateway)`, permitido pela PEP 544), e a seta passa a ir do detalhe para a abstração. Com isso, a conformidade é verificada na definição da classe e não só no ponto de uso. Resultado: I = 0,50, fora da zona. Na `main`, o adaptador também traduz os erros do gateway para os erros declarados no port, o que reforça essa dependência.

**Revisão 2: `config` sai da zona de dor por leitura crítica, não por import.** O plano esperava que reduzir o Ca de `config` bastasse. Ao fim da refatoração, o Ca caiu de 6 para 2 (`main` e `tickets`), mas o componente continua em (I = 0, A = 0). Qualquer módulo concreto sem dependências e com pelo menos um dependente cai ali pela fórmula. O que tornava `config` perigoso na v1 era o conteúdo: nomes físicos, URLs e chaves de provider, que mudam a cada troca de modelo. Esse conteúdo foi para o gateway. O que sobrou (endereço e chave do gateway, lidos do ambiente, nomes lógicos e parâmetros do relatório) só muda junto com o contrato da aplicação. Por isso ele é declarado estável por natureza no ADR da métrica, ao lado de `schemas`, em vez de ganhar um import artificial para sair da zona.

**Revisão 3: gateway mínimo na tag, resiliência depois.** O plano original subia o gateway já com retries e fallbacks. Os testes exploratórios contra o `/admin/calls` mostraram que retry, fallback e cooldown do LiteLLM mudam quantas chamadas chegam ao provider em cada cenário. Misturar isso com a refatoração tornaria a caracterização ambígua ("mudou o comportamento ou só a infraestrutura?"). A `v2-decoupled` leva o mínimo exigido (nomes lógicos, uma chave virtual, um modelo `large` por capacidade). Resiliência e governança entram depois da tag, cada uma com sua evidência.

## Handoff para o agente

Agente: Claude Code (modelo Claude Opus 5.5), com acesso ao repositório e ao compose.

O que foi entregue ao agente:

1. Este plano (alvos, estratégia por componente, critério de pronto).
2. A suíte `tests/characterization/`, com a regra de que ela não pode ser alterada (o critério é `git diff v1-coupled -- tests/characterization/` vazio).
3. O script `metrics/coupling.py` e a régua do requisito 3.
4. As restrições verificáveis: nenhum `gpt-fake-*`/`claude-fake-*` nem chave de provider em `app/`; o serviço `app` sem as chaves no ambiente; o adaptador do gateway importado só por `main`; mesmas rotas e mesmos modos de resposta.

Protocolo de aceite, repetido a cada passo (piloto, depois cada feature):

```
docker compose up -d --build --wait
.venv/bin/pytest tests/characterization -q            # 21 passed, sem editar a suíte
.venv/bin/python metrics/coupling.py app/helpdesk --name _check --no-plot
grep -rE "gpt-fake|claude-fake|FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY" app/   # vazio
curl -s "localhost:8090/admin/calls?last=50"         # mesmo provider/modelo large por tarefa
```

O que foi aceito e o que foi rejeitado:

- Rejeitado: a primeira versão do adaptador (estrutural, sem importar o port). Os testes passaram, mas a métrica acusou a zona de dor (D = 1,00). Os testes sozinhos teriam aceitado. Deu origem à Revisão 1.
- Rejeitado: uma rodada de testes com 10 falhas logo depois de trocar o gateway para a configuração mínima. A causa era ambiente (o Docker Desktop caiu no meio da execução, e o `/admin/reset` do provider recusava conexão), não código. A suíte foi rodada de novo com o ambiente de pé antes de qualquer conclusão: 21 passaram, sem mudança de código.
- Aceito: as outras três features no mesmo molde do piloto (`ReplySuggester`, `OrderExtractor`, `TopicsReporter`), com o prompt (`TASK: ...`) montado dentro de cada feature e não no adaptador. O adaptador só transporta, e a feature é dona do que pede. O `TopicsReporter` recebe a leitura de tickets (`tickets.in_period`) por construtor, em vez de importar o módulo.
- Aceito: remoção de `llm.py` e do SDK `anthropic` de `app/requirements.txt`. A aplicação fala um único formato (Chat Completions) com o gateway, e o gateway traduz para o formato nativo de cada provider.

Resultado na `v2-decoupled` ([CSV](../metrics/results/v2-decoupled.csv), [gráfico](../metrics/results/v2-decoupled.png)): `llm` deixou de existir; `ports` em (I = 0, A = 1); features em I = 0,67 e D = 0,33; `adapters.gateway` em I = 0,50; na zona de dor só `config` e `schemas`, os dois declarados estáveis por natureza (Revisão 2). Suíte de caracterização: 21 passaram, sem alteração.
