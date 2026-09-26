# Da integração frágil à arquitetura resiliente: IA em produção num helpdesk

## Descrição

Neste desafio você recebe uma aplicação com IA do jeito que ela costuma nascer (acoplada, síncrona, com o provider espalhado pelo código), mede o quanto isso custa e a leva, com decisões registradas e evidência medida, até um estado em que trocar de modelo ou de provider é uma mudança de configuração, e não um projeto.

A aplicação é entregue em Python com FastAPI, e a evolução continua nessa stack. As ferramentas (gateway, testes, medição) ficam a seu critério. As decisões de arquitetura, como o modo de execução de cada feature e a política de fallback, partem das características do contrato e precisam cumprir os critérios de aceite. Cada decisão precisa estar registrada, justificada pelos fatos do problema e comprovada por um efeito observável. O escopo é o que está descrito aqui: componentes, features ou camadas que os requisitos não pedem não são avaliados e só aumentam o que você precisa justificar.

## Cenário

O helpdesk de uma loja online colocou IA em quatro pontos do atendimento. Quem fez foi rápido: cada feature chama o SDK do provider direto de dentro do código, uma usa a OpenAI e outra a Anthropic porque "funcionou melhor no teste", as chaves ficam na configuração da aplicação e tudo responde de forma síncrona. Esse código é o `app/` do repositório base.

Três meses depois, a conta chegou. O relatório mensal de temas nunca termina: a requisição morre no proxy da empresa. O atendente olha 15 segundos para uma tela parada esperando a sugestão de resposta. Na última instabilidade de um provider, metade do helpdesk parou junto. E trocar um modelo por outro mais barato exige deploy, porque o nome do modelo está no código.

Você é a pessoa de arquitetura que vai conduzir essa virada. Primeiro, reproduz as dores do sistema que herdou e mede o problema. Depois, planeja, refatora com um agente de IA usando a métrica como juiz, coloca um gateway na frente dos providers e decide, feature por feature, como cada chamada deve ser executada. No fim, qualquer pessoa do time precisa conseguir trocar um modelo, derrubar um provider ou estourar um orçamento e ver o sistema se comportar exatamente como os ADRs dizem.

## Sobre o foco do desafio

O foco é arquitetura, não prompt nem qualidade de texto gerado. Por isso o repositório base traz um provider simulado (`provider-fake`) que imita as APIs da OpenAI e da Anthropic, responde de forma determinística, cobra tokens, tem latência realista e falha sob comando. O fluxo do avaliador roda inteiramente contra ele, sem chave paga. Você pode usar providers reais durante o desenvolvimento se quiser, mas nada da entrega pode depender deles.

Algumas situações no starter travam de propósito. Cada uma tem uma pista (seção Fricções propositais): a intenção é você descobrir a solução, não sofrer no escuro.

## Objetivo

Entregar, num fork público do repositório base, o diagnóstico da aplicação recebida, as decisões de arquitetura registradas (ADRs e plano de refatoração), a medição de acoplamento das três versões e a aplicação evoluída atrás de um AI Gateway, com os modos de execução decididos. O detalhe de cada peça está em Entregável, e os caminhos, em Estrutura obrigatória do entregável.

## Repositório base

https://github.com/devfullcycle/desafio-arquitetura-era-ia-1

Faça o fork e trabalhe na `main` do seu fork. Para conhecer o terreno:

```
cp .env.example .env
docker compose up -d --build --wait
curl -s localhost:8000/health
curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}'
```

O compose sobe o `provider-fake`, a borda (serviço `edge`) e a aplicação (serviço `app`). O `--wait` faz o comando só retornar quando os serviços estiverem saudáveis.

No seu fork, o `README.md` passa a ser o seu (seções obrigatórias em Entregável). O enunciado continua disponível no repositório base.

## Contexto

### O que o repositório base traz

- `provider-fake/` (não alterar): o provider simulado, em container, exposto em `http://localhost:8090` (dentro do compose, `http://provider-fake:8090`). Documentação completa em `provider-fake/README.md`.
- `app/` (entregue; é o que você evolui): a aplicação do helpdesk, descrita em A aplicação existente.
- `edge/` (não alterar): a borda, um nginx que representa o proxy reverso da empresa. Ele é a porta de entrada oficial do helpdesk em `http://localhost:8000` e encaminha tudo para `http://app:8080`. O avaliador usa sempre a borda.
- `data/tickets.jsonl` (não alterar): 5.000 tickets de agosto de 2026, um JSON por linha, com os campos `id`, `created_at`, `customer_id` e `text`.
- `docs/adr/0000-template.md`: um template de ADR, que você pode seguir ou substituir.
- `compose.yaml` e `.env.example`: a base que você estende. As chaves dos providers estão no `.env.example` e chegam hoje à aplicação por `env_file`.

### O provider simulado

Ele imita dois providers distintos, cada um com seu formato nativo:

| Provider | Base URL (dentro do compose) | Formato | Autenticação | Modelos |
|---|---|---|---|---|
| `openai` | `http://provider-fake:8090/openai/v1` | Chat Completions (`/chat/completions`) | `Authorization: Bearer <FAKE_OPENAI_KEY>` | `gpt-fake-large`, `gpt-fake-mini` |
| `anthropic` | `http://provider-fake:8090/anthropic` | Messages (`/v1/messages`) | `x-api-key: <FAKE_ANTHROPIC_KEY>` | `claude-fake-large`, `claude-fake-mini` |

Os SDKs oficiais das duas empresas funcionam contra ele apontando a base URL. Os dois formatos suportam streaming (SSE) no padrão de cada provider. As chaves aceitas estão no `.env.example`.

O que você precisa saber para o desafio (o resto está no README do provider):

- O modelo simulado entende quatro tarefas. A primeira linha da mensagem do usuário deve ser `TASK: classify`, `TASK: suggest`, `TASK: topics` ou `TASK: extract`, seguida do conteúdo. O formato exato de entrada e saída de cada tarefa está no README do provider. O texto do prompt não é avaliado.
- Os modelos `large` dos dois providers são equivalentes entre si. Os modelos `mini` são mais rápidos e baratos, e piores: a diferença de qualidade aparece de forma concreta em pelo menos uma das tarefas. Descobrir qual e o quanto importa é parte do desafio.
- Cada modelo tem janela de contexto, preço por token, tempo até o primeiro token e velocidade de geração declarados no README do provider. A resposta traz `usage` com os tokens consumidos.
- Endpoints de administração controlam o comportamento e registram tudo:

```
POST /admin/failures   {"provider": "openai", "model": "gpt-fake-large", "mode": "error_500"}
                       mode: normal | error_500 | error_429 | timeout | slow | midstream_error
                       "model" é opcional; sem ele, vale para o provider inteiro
GET  /admin/calls      últimas chamadas recebidas: provider, model, task, stream, status, tokens, duração
POST /admin/reset      volta tudo ao modo normal e limpa o registro de chamadas
```

O `/admin/calls` é o instrumento de prova do desafio: é por ele que o avaliador confirma para qual provider e modelo cada requisição foi de fato, quantas tentativas aconteceram e se uma chamada recusada chegou ou não ao provider.

### A aplicação existente

Python 3.12 com FastAPI e os SDKs oficiais `openai` e `anthropic`. O código fica em `app/helpdesk/`:

- `main.py`: as rotas HTTP das quatro features e o `GET /health`
- `schemas.py`: os tipos de entrada e saída (pydantic)
- `config.py`: credenciais dos providers, base URLs, nomes dos modelos físicos de cada feature e parâmetros do relatório
- `llm.py`: um cliente de SDK por provider e as funções `call_openai` e `call_anthropic`
- `classification.py`, `suggestion.py`, `extraction.py` e `report.py`: uma feature cada
- `tickets.py`: a leitura de `data/tickets.jsonl`, montado no container em `/data`

F1 e F4 usam o provider `openai`; F2 e F3 usam o `anthropic`, cada um no seu formato nativo. A F3 divide os tickets do período em lotes de 150 e chama o modelo para cada lote, um depois do outro, porque o período inteiro não cabe na janela de contexto. Nenhuma chamada tem timeout ou política de retry configurados: valem os padrões dos SDKs.

### O contrato do helpdesk

A aplicação escuta em `8080` dentro do compose, como serviço `app`. As quatro features são fixas no que recebem e no resultado que produzem. Na aplicação recebida, as quatro respondem de forma síncrona, com o resultado no corpo da resposta. A forma de entrega (síncrono, streaming ou assíncrono) é o que pode mudar na `main` (requisito 6).

| Feature | Rota | Entrada | Resultado | Características do negócio |
|---|---|---|---|---|
| F1 Classificar ticket | `POST /tickets/classification` | `{"ticket_id", "text"}` | `{"ticket_id", "category", "priority"}` | Roda na abertura do ticket, com o cliente esperando a confirmação na tela. Saída curta, de valores fixos. |
| F2 Sugerir resposta | `POST /tickets/reply-suggestion` | `{"ticket_id", "text"}` | `{"ticket_id", "suggestion"}` | O atendente está olhando a tela e começa a ler e editar assim que o texto aparece. Saída longa. |
| F3 Relatório de temas | `POST /reports/topics` | `{"start": "2026-08-01", "end": "2026-08-31"}` | `{"start", "end", "total_tickets", "topics": [{"topic", "count", "examples": [ids]}]}` | Lê os tickets do período em `data/tickets.jsonl`. O mês inteiro são 5.000 tickets. Quem pede é um painel interno no navegador, que não expõe callback. Ninguém fica esperando olhando para ele. |
| F4 Extrair dados do pedido | `POST /tickets/extraction` | `{"ticket_id", "text"}` | `{"ticket_id", "order_number", "product"}` | Alimenta uma automação de troca e devolução sem revisão humana. Um campo errado gera uma troca errada, que custa frete, estoque e cliente. |

Valores permitidos: `category` em `delivery`, `payment`, `exchange_return`, `product_defect`, `other`; `priority` em `low`, `medium`, `high`; `order_number` no formato `#` seguido de 6 dígitos, ou `null` quando o ticket não cita pedido; `product` texto ou `null`.

A aplicação também expõe `GET /health`, que responde `200`.

### Fricções propositais

São situações intencionais. Cada uma tem uma pista.

- A borda tem paciência limitada. Ela encerra a requisição com `504` quando a aplicação passa 30 segundos sem enviar nenhum byte. Pista: em uma cadeia de proxies, o timeout mais curto vence, e normalmente não é o seu. Leia `edge/nginx.conf`.
- Desistir não é cancelar. Quando a borda devolve `504`, a aplicação recebida continua trabalhando. Pista: peça o relatório do mês, espere o `504` e acompanhe o `/admin/calls` pelos minutos seguintes. Quem está pagando por esses tokens?
- Os padrões dos SDKs não foram pensados para o seu orçamento de latência. Pista: descubra qual é o timeout e quantos retries os SDKs `openai` e `anthropic` fazem por padrão, e compare com os 30 segundos da borda.
- O modelo barato não é tão bom. Pista: antes de decidir onde aceitar um fallback com modelo fraco, chame cada tarefa nos dois tamanhos e compare as saídas.

## Tecnologias obrigatórias

- Docker e Docker Compose v2
- Git, com as tags exigidas publicadas no fork (`git push --tags`)
- Um AI Gateway self-hosted rodando como serviço `gateway` no compose. O LiteLLM Proxy, visto no curso, é a sugestão; qualquer outro vale se entregar as capacidades do requisito 5. Gateways SaaS não são aceitos, porque o avaliador precisa subir tudo localmente.
- A aplicação continua em Python 3.12 com FastAPI. Biblioteca de testes e ferramenta de medição à sua escolha.

É proibido alterar `provider-fake/`, `edge/` e `data/`.

## Requisitos

Cada requisito está amarrado a um conceito dos módulos 01 a 04. Leia o porquê antes da tarefa: é ele que diz se você resolveu de verdade ou só cumpriu tabela.

### 1. Conhecer a aplicação recebida

Por quê. Não dá para afirmar que uma arquitetura melhorou sem um ponto de partida medido, e não dá para decidir nada sem entender onde a dor mora. O cenário descreve quatro dores; antes de mexer em qualquer linha, você as reproduz e as transforma em fatos observáveis. É desse diagnóstico que os seus ADRs vão partir.

Tarefa.

- Suba o ambiente e exercite as 4 features pela borda (`localhost:8000`)
- Reproduza as quatro dores do cenário, usando os modos de falha do provider simulado quando for o caso: o relatório do mês não chega; a sugestão de resposta deixa o atendente esperando sem ver nada; com um provider fora do ar ou travado, parte do helpdesk para; trocar o modelo de uma feature exige mudar código e reconstruir a aplicação
- Registre o diagnóstico na seção "Diagnóstico da v1" do README: para cada dor, o comando executado, o que foi observado (status, tempo, registros de `/admin/calls`) e em qual trecho de `app/` a causa está
- Não altere `app/` nesta etapa. A única exceção é demonstrar a dor da troca de modelo: você pode alterar `app/` temporariamente para isso, desde que desfaça a alteração antes da tag `v1-coupled`.

### 2. Testes de caracterização

Por quê. Refatoração é mudança de estrutura sem mudança de comportamento; se o comportamento mudou, foi reescrita disfarçada. Os testes de caracterização (Feathers) fixam o que o sistema faz hoje e são a rede de segurança que permite entregar a refatoração a um agente de IA sem medo.

Tarefa.

- Escreva, em `tests/characterization/`, uma suíte que exercita as 4 features pela API HTTP e fixa o comportamento observado da `v1-coupled`, incluindo pelo menos um caso de erro de entrada por feature. A suíte fixa o corpo das respostas (campos e valores), não só o status HTTP.
- A suíte roda com um único comando documentado no README, contra a aplicação no compose
- Quando a suíte passar contra a aplicação recebida, marque o commit com a tag `v1-coupled`. Nesse commit, `app/` é exatamente o do repositório base.
- A suíte é a mesma nas tags `v1-coupled` e `v2-decoupled` e passa nas duas. Na `main`, ela pode ser atualizada para o contrato novo das features que mudaram de modo de execução (requisito 6); a igualdade é exigida só entre as duas tags.

### 3. Medir antes de mexer

Por quê. Sem número, "isso está acoplado demais" é opinião, e a discussão vira preferência pessoal. O módulo 02 transforma opinião em medida com a Main Sequence: cada componente vira um ponto no gráfico A × I, e a refatoração ganha um critério de pronto observável.

Tarefa.

- Escreva (ou adapte) um script em `metrics/` que recebe o caminho do código a medir (a pasta `app/helpdesk/` de qualquer checkout) e calcula, por componente, Ca, Ce, I, A e D segundo a régua abaixo
- O script grava `metrics/results/<name>.csv` com o cabeçalho exato `component,ca,ce,i,a,d` e um gráfico A × I com a Main Sequence traçada
- A régua é fixa, para que as medições de todos sejam comparáveis: componente é cada módulo `.py` de `app/helpdesk/`, incluindo subpastas, identificado pelo caminho com pontos (ex.: `adapters.gateway`), exceto os `__init__.py`; uma dependência é um import, relativo ou absoluto, que resolve para outro componente (ex.: `from ..ports import Gateway` ou `from helpdesk import config`); bibliotecas externas e da biblioteca padrão não contam; Ca é quantos componentes importam este, Ce é quantos este importa; I = Ce / (Ce + Ca), ou 0 quando os dois são zero; A é o número de classes abstratas (que herdam de `typing.Protocol` ou `abc.ABC`) dividido pelo total de classes do módulo, ou 0 quando o módulo não tem classes; D = |A + I - 1|; valores arredondados para 2 casas.
- Componentes concretos que quase nunca mudam (ex.: tipos de valor do domínio) caem na zona de dor pela fórmula sem serem um problema real. Se for o caso, declare-os no ADR da métrica como estáveis por natureza, com justificativa. É uma leitura crítica da métrica, não uma brecha: o componente que chama o gateway e os componentes das features não entram nessa lista.
- Meça a `v1-coupled` e versione o resultado (`metrics/results/v1-coupled.csv` e o gráfico). O script nasce depois da tag: para medir uma tag, rode o script da sua branch sobre um checkout dela (ex.: `git worktree add ../v1 v1-coupled`).

### 4. Planejar, pilotar e refatorar com agente (tag `v2-decoupled`)

Por quê. O agente de IA é persuasivo, mas não é confiável para avaliar o próprio trabalho. O ciclo do módulo 02 resolve isso casando o agente, que não é determinístico, com testes e métrica, que são. E o primeiro plano quase nunca sobrevive ao contato com a medição: por isso existe piloto antes de escalar.

Tarefa.

- Escreva `docs/refactoring-plan.md` com os componentes-alvo, a estratégia para cada um (aumentar A, reduzir Ca, inverter a dependência, compor em vez de herdar) e o critério de pronto baseado na métrica
- Execute um piloto em um único componente antes de escalar, e registre no plano a medição antes e depois do piloto
- Registre no plano pelo menos uma revisão (o que mudou do plano original e por quê, com base no que o piloto ou a medição mostrou)
- Faça a refatoração com um agente de IA de sua escolha. Registre no plano como foi o handoff: o que você entregou ao agente, como a métrica e os testes foram usados para aceitar ou rejeitar o que ele produziu.
- Coloque o gateway na frente dos providers nesta etapa. O mínimo exigido na `v2-decoupled` é: a aplicação chama os modelos só pelo gateway, usando nomes lógicos e uma chave do próprio gateway, sem as chaves dos providers. Governança, resiliência e fallback (requisito 5) podem entrar depois da tag.
- Nesta tag, o comportamento externo não muda: mesmas rotas, mesmos modos de resposta, suíte de caracterização passando sem alteração. Mantenha um modelo `large` por trás de cada capacidade: os dois `large` são equivalentes e dão a mesma saída, mas um `mini` muda as saídas que a suíte fixou.
- Meça com o mesmo script e versione `metrics/results/v2-decoupled.csv` e o gráfico
- Marque o commit com a tag `v2-decoupled`

### 5. O AI Gateway

Por quê. Na `v1`, a aplicação depende de detalhes concretos e voláteis: o provider, o nome do modelo, o formato da API, a credencial. É acoplamento no sentido exato do módulo 02, e o gateway é a inversão de dependência aplicada à IA: a aplicação passa a pedir uma capacidade, e quem decide o modelo físico é a infraestrutura. Credencial, custo, limites e resiliência saem de cada serviço e vão para um lugar só.

Tarefa. O gateway roda como serviço `gateway` no compose, com a configuração versionada em `gateway/`, e entrega:

- Capacidades lógicas: a aplicação só conhece nomes lógicos definidos por você. Nenhum nome de modelo físico (`gpt-fake-*`, `claude-fake-*`) aparece em `app/`.
- Credenciais fora da aplicação: as chaves dos providers vivem só no gateway. A aplicação usa uma chave do próprio gateway (virtual key ou equivalente).
- Troca de modelo por configuração: mudar o modelo físico por trás de uma capacidade exige alterar só a configuração do gateway e reiniciar só o gateway. A aplicação não é reconstruída nem reiniciada.
- Governança mínima: pelo menos uma chave com orçamento (budget) e uma com limite de requisições. Uma requisição fora do limite é recusada pelo gateway antes de chegar ao provider.
- Resiliência: timeout explícito, retry limitado e com backoff para falhas transitórias, e fallback técnico para um destino equivalente em outro provider, para toda capacidade. O número máximo de tentativas por destino (primário, fallback técnico e, se houver, modelo fraco) é declarado no README.
- Fallback com modelo fraco: decidido feature por feature. Para cada feature, você decide se, sem nenhum modelo `large` disponível, vale responder com um `mini` ou falhar explicitamente. Essa decisão é de produto, não só de infra, e precisa estar no ADR com a evidência que a sustenta.

Cada mecanismo pode morar no gateway ou na aplicação, desde que o efeito observável aconteça e o ADR diga onde ele está.

Pistas de ferramenta, para não perder tempo com o que não é arquitetura: gateways que oferecem chaves virtuais e orçamento costumam precisar de um banco de dados, e as chaves precisam ser criadas sem passo manual; o gateway pode não conhecer o preço dos modelos simulados e, nesse caso, calcula custo zero e o orçamento nunca estoura (os preços estão no README do provider); e retries configurados em mais de um lugar (SDK, gateway, aplicação) se multiplicam, o que o `/admin/calls` mostra na hora.

### 6. Decidir o fluxo de cada feature (`main`)

Por quê. Uma chamada a LLM não se comporta como uma chamada HTTP comum: demora segundos, custa por token, chega aos poucos e prende conexões. Escolher entre síncrono, streaming e assíncrono é decisão arquitetural, e a pergunta certa não é "qual adotar", é "qual para cada caso de uso". Cada escolha tem custo: o assíncrono ganha capacidade e paga com estado distribuído e peças a operar.

Tarefa.

- Para cada feature, decida o modo de execução a partir das características do contrato e registre as quatro decisões num único ADR de execução, com uma seção por feature e a pergunta da árvore de decisão que sustentou cada uma ("alguém está esperando agora?", "cabe no orçamento de latência?", "é consumível aos poucos?")
- Meça a `main` com o mesmo script e versione `metrics/results/main.csv` e o gráfico

A versão final precisa cumprir os requisitos de experiência abaixo, medidos sempre pela borda (`localhost:8000`). Os limites de tempo valem com o provider simulado no modo normal, salvo quando o item diz outra coisa.

- F1 entrega o resultado completo em até 3 s
- F2 mostra o primeiro trecho do texto da sugestão em até 1,5 s, e o texto continua chegando até completar
- F3 aceita o pedido do mês inteiro (`2026-08-01` a `2026-08-31`) respondendo em até 1 s, e o relatório completo, cobrindo os 5.000 tickets, fica disponível depois para quem pediu
- Nenhuma requisição, de nenhuma feature, termina em `504` da borda, inclusive nos cenários de falha do provider descritos nos critérios
- Se usar streaming: `Content-Type: text/event-stream`, e um erro no meio do stream chega ao cliente como evento `error` dentro do próprio stream, no formato de Contratos sugeridos (o status HTTP já foi enviado). O modo `midstream_error` do provider simulado provoca exatamente essa falha.
- Se usar Asynchronous Request-Reply: `202 Accepted` com os headers `Location` e `Retry-After`; a URL de status responde `200` com o estado (`pending`, `running` ou `failed`, este com o motivo) enquanto a tarefa não termina com sucesso, e `303 See Other` apontando para o resultado quando ela chega a `done`. Uma tarefa que não consegue terminar chega a `failed` em até 60 s e nunca fica presa em `running`.
- Qualquer feature síncrona tem timeout explícito, e nenhuma fica pendurada quando o provider trava: responde com sucesso (via fallback) ou com erro explícito em até 15 s

A mudança de modo de resposta é uma evolução deliberada do contrato, e por isso acontece depois da tag `v2-decoupled`. Atualize (ou complemente) os testes na `main` para o novo contrato. A suíte de caracterização nas tags continua sendo o registro do comportamento antigo.

### 7. Decisões nos três níveis

Por quê. O mesmo termo "arquiteto" muda de significado conforme o nível: corporativa decide qual problema resolver, solução decide como resolver e software decide como construir. Decisões de IA caem nos três, e localizar cada uma no nível certo diz quem precisa participar dela e quanto tempo ela deve durar.

Tarefa.

- Registre as decisões em `docs/adr/`, um arquivo por decisão, com contexto, opções consideradas, decisão e consequências. Cada ADR tem uma linha `Nível: corporativa`, `Nível: solução` ou `Nível: software`.
- Os ADRs cobrem no mínimo: a escolha e a posição do gateway; as capacidades lógicas e o mapeamento para modelos físicos; o modo de execução, num ADR único com uma seção por feature; a política de fallback (técnico e com modelo fraco), que pode ser um ADR único com uma seção por feature; a governança de chaves, orçamentos e limites; a leitura da métrica, com as exceções declaradas (se houver)
- Há pelo menos uma decisão em cada um dos três níveis (ex.: uma política de quais providers a empresa aceita, ou um teto de gasto mensal com IA, cabe no nível corporativo)

## Restrições (não negociáveis)

- `provider-fake/`, `edge/` e `data/` não são alterados. As fricções são resolvidas na sua aplicação, no seu gateway ou no seu compose.
- Na `v2-decoupled` e na `main`, toda chamada a modelo passa pelo gateway. O código em `app/` não chama o `provider-fake` diretamente. Os testes podem usar os endpoints `/admin`.
- Na `v2-decoupled` e na `main`, as chaves `FAKE_OPENAI_KEY` e `FAKE_ANTHROPIC_KEY` não aparecem em `app/` nem no ambiente do serviço `app`.
- A refatoração evolui o código de `app/`. Reescrever a aplicação do zero, ou em outra linguagem, descaracteriza a entrega.
- A régua da métrica é a do requisito 3, nas três medições. Um script que mede com outra régua invalida a comparação.
- O fluxo do avaliador não depende de provider real nem de qualquer serviço externo além das imagens públicas usadas no compose.
- Cada serviço que você adicionar ao compose além de `app` e `gateway` (fila, banco, worker) precisa de um ADR que justifique sua existência a partir de um requisito.
- Se encontrar uma limitação real na ferramenta de gateway escolhida, documente-a no ADR e resolva na aplicação em vez de desistir do efeito exigido.

## Fora de escopo

- Cache de qualquer tipo, RAG, observabilidade além de logs, evals de qualidade e segurança (prompt injection, guardrails). São temas dos módulos seguintes e do próximo desafio.
- Qualidade do texto gerado e escrita de prompts. O provider é simulado; o texto do prompt não é avaliado.
- Autenticação dos usuários do helpdesk, frontend e deploy em nuvem.
- Sobreviver a um reinício da aplicação com tarefas assíncronas em andamento. Se você persistir estado, ótimo, mas não é cobrado.
- Cancelar a geração no provider quando o cliente fecha a conexão de streaming.
- Batch API real dos providers. O provider simulado não a implementa.
- Deduplicar pedidos repetidos de relatório para o mesmo período.
- Circuit breaker. Timeout, retry e fallback são exigidos; circuit breaker não é cobrado.

## Contratos sugeridos

Os exemplos abaixo são o formato de referência de cada modo e a base dos critérios. Siga-os; se precisar de algum campo adicional, documente no README.

Síncrono:

```
POST /tickets/classification
{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}

200 OK
{"ticket_id": "TK-00042", "category": "delivery", "priority": "high"}
```

Streaming:

```
POST /tickets/reply-suggestion
{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}

200 OK
Content-Type: text/event-stream

data: {"chunk": "Olá! Sinto muito pelo atraso"}
data: {"chunk": " na entrega do seu pedido"}
...
event: end
data: {"ticket_id": "TK-00042"}
```

Falha no meio do stream (o status `200` já foi enviado; o stream termina logo depois do evento):

```
data: {"chunk": "Olá! Sinto muito pelo atraso"}
...
event: error
data: {"ticket_id": "TK-00042", "message": "A geração foi interrompida"}
```

Assíncrono:

```
POST /reports/topics
{"start": "2026-08-01", "end": "2026-08-31"}

202 Accepted
Location: /reports/topics/status/7f3a
Retry-After: 5

GET /reports/topics/status/7f3a
200 OK   {"state": "running", "progress": "1800/5000"}

GET /reports/topics/status/7f3a
303 See Other
Location: /reports/topics/7f3a

GET /reports/topics/7f3a
200 OK   {"start": "2026-08-01", "end": "2026-08-31", "total_tickets": 5000, "topics": [...]}
```

## Critérios de Aceite

A entrega é avaliada contra os critérios abaixo. Todos são obrigatórios.

Diagnóstico e caracterização

☐ A seção "Diagnóstico da v1" do README registra as quatro dores do cenário, cada uma com o comando executado, o resultado observado e o trecho de `app/` onde está a causa
☐ A tag `v1-coupled` existe no fork, e nela `app/` é idêntico ao do repositório base
☐ A suíte de caracterização fixa o corpo das respostas das 4 features (não só o status), roda com o comando documentado e passa na `v1-coupled` e na `v2-decoupled`
☐ `git diff v1-coupled v2-decoupled -- tests/characterization/` não mostra diferença

Métrica de acoplamento

☐ `metrics/results/` contém, para `v1-coupled`, `v2-decoupled` e `main`, um CSV com o cabeçalho `component,ca,ce,i,a,d` e um gráfico A × I com a Main Sequence
☐ Rodar o script da `main` sobre um checkout da `v1-coupled` reproduz o CSV versionado para essa tag
☐ Os CSVs seguem a régua do requisito 3, e a medição da `v1-coupled` bate com a recalculada pelo avaliador
☐ Na `main`, nenhum componente está na zona de dor (ao mesmo tempo A < 0,5, I < 0,5 e D ≥ 0,5), exceto os declarados no ADR da métrica como estáveis por natureza, com justificativa; o componente que chama o gateway e os componentes das features não podem ser exceção
☐ Na `main`, o código que chama o gateway (SDK ou cliente HTTP) fica em um único componente de `app/`, identificado no README, e nenhum componente de feature o importa; só o ponto de composição da aplicação (onde os componentes são montados, ex.: `main.py`) pode depender dele

Plano e refatoração

☐ `docs/refactoring-plan.md` contém os componentes-alvo, a estratégia de cada um, o critério de pronto, o piloto com medição antes e depois, pelo menos uma revisão justificada e o registro do handoff para o agente
☐ A tag `v2-decoupled` existe, e nela a aplicação já chama os modelos exclusivamente pelo gateway

Gateway

☐ `grep -rE "gpt-fake|claude-fake" app/` não retorna nada na `main`
☐ `grep -rE "FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY|sk-fake-openai|sk-ant-fake" app/` não retorna nada, `docker compose exec app env` não contém as chaves dos providers, e a definição do serviço `app` em `docker compose config` não recebe essas chaves por variável, `env_file` ou arquivo montado
☐ Seguindo o README, trocar o modelo físico de uma capacidade exige alterar só a configuração do gateway e reiniciar só o serviço `gateway`; a próxima chamada aparece em `/admin/calls` com o novo modelo, e o serviço `app` não foi reiniciado
☐ O roteiro de governança do README, executado como descrito, mostra uma requisição recusada por orçamento e outra recusada por limite de requisições, e o número de chamadas em `/admin/calls` não aumenta com as requisições recusadas
☐ Com o provider primário de uma capacidade em `error_500`, a feature correspondente responde com sucesso, e `/admin/calls` mostra as tentativas no primário (no máximo o número declarado no README) seguidas do sucesso no destino equivalente do outro provider
☐ Com os dois modelos `large` em `error_500`, cada uma das 4 features se comporta exatamente como declarado na tabela de fallback do README

Fluxos de chamada (medidos pela borda, `localhost:8000`)

☐ F1 entrega o resultado completo em até 3 s
☐ `curl -N` na F2 mostra o primeiro trecho do texto em até 1,5 s, e o primeiro trecho chega antes da metade do tempo total da resposta
☐ O pedido da F3 para `2026-08-01` a `2026-08-31` responde em até 1 s, e o relatório obtido depois tem `total_tickets` igual a 5000, com as chamadas da tarefa `topics` que o produziram registradas em `/admin/calls`
☐ Com os dois providers inteiros em `error_500`, um novo pedido de relatório da F3 chega a um estado de falha visível ao cliente, com motivo, em até 60 s
☐ Com o provider primário da F1 em `timeout`, a F1 responde (com sucesso via fallback ou com erro explícito) em até 15 s
☐ Nenhuma das verificações acima produz `504` da borda
☐ Cada modo usado segue o contrato do padrão descrito no requisito 6; se a F2 usa streaming, com o provider primário dela em `midstream_error` o cliente recebe um evento `error` no formato de Contratos sugeridos

Decisões

☐ `docs/adr/` contém os ADRs mínimos listados no requisito 7, cada um com a linha `Nível:` preenchida
☐ Existe pelo menos um ADR em cada nível (corporativa, solução e software)
☐ O ADR de fallback traz, para cada feature, a decisão sobre o modelo fraco e a evidência observada no provider simulado que a sustenta
☐ O ADR de execução tem uma seção por feature, cada uma citando as características do contrato que levaram à decisão, e o comportamento implementado bate com ele

README e consistência geral

☐ O README contém todas as seções listadas em Entregável
☐ `cp .env.example .env && docker compose up -d --build --wait` na `main` sobe tudo, e `curl -s localhost:8000/health` logo em seguida retorna 200, sem passos manuais adicionais
☐ `provider-fake/`, `edge/` e `data/` não foram alterados
☐ Todo serviço do compose além de `provider-fake`, `edge`, `app` e `gateway` tem um ADR que o justifica a partir de um requisito

## Estrutura obrigatória do entregável

```
.
├── README.md                      (substituído pelo aluno)
├── compose.yaml                   (você estende)
├── .env.example                   (você estende)
├── provider-fake/                 (não alterar)
├── edge/                          (não alterar)
├── data/
│   └── tickets.jsonl              (não alterar)
├── app/                           (entregue; você evolui) a aplicação do helpdesk
├── gateway/                       (você cria) configuração do gateway
├── tests/
│   └── characterization/          (você cria)
├── metrics/                       (você cria) o script
│   └── results/                   v1-coupled, v2-decoupled e main (CSV + gráfico)
└── docs/
    ├── refactoring-plan.md        (você cria)
    └── adr/                       (você cria) um arquivo por decisão
```

Outros arquivos que sua solução precisar (Dockerfiles, scripts, testes da `main`, serviços extras como fila ou banco) podem ficar onde fizer sentido, desde que sejam declarados no compose e no README.

## Entregável

Você entrega um link: o seu fork público no GitHub, com a versão final na branch `main` e as tags `v1-coupled` e `v2-decoupled` publicadas. As tags marcam estados reais da evolução: uma tag sobre um commit que não cumpre o que o requisito dela exige não é aceita. Dentro do fork, a entrega tem quatro partes.

As decisões (documentos):

- `README.md` com o diagnóstico da aplicação recebida e as tabelas das suas decisões (seções obrigatórias listadas abaixo)
- `docs/adr/`: um arquivo por decisão, cada um marcado com o nível (corporativa, solução ou software)
- `docs/refactoring-plan.md`: o plano, o piloto, a revisão do plano e o registro do handoff para o agente de IA

As provas (medições):

- `metrics/`: o script que mede o acoplamento e os resultados das três versões (CSV e gráfico A × I)

A execução (código e configuração):

- `app/`: a aplicação recebida, refatorada, chamando os modelos só pelo gateway e entregando cada feature no modo que você decidiu
- `gateway/`: a configuração do gateway (capacidades, fallback, chaves, orçamentos e limites)
- `compose.yaml`: sobe tudo com um único comando
- `tests/characterization/`: os testes que garantem que a refatoração não mudou o comportamento

Os marcos no git:

- tag `v1-coupled`: a aplicação como você recebeu, mais a suíte de caracterização
- tag `v2-decoupled`: a aplicação refatorada, já atrás do gateway, com o mesmo comportamento
- branch `main`: a versão final, com o modo de execução de cada feature decidido

Como a entrega é avaliada: o corretor clona o seu fork, sobe o ambiente com um comando e provoca situações pelo provider simulado. Ele derruba um provider, derruba os modelos bons, troca um modelo e estoura um orçamento, e em cada caso confere se o sistema faz exatamente o que os seus ADRs e o seu README dizem. Em resumo: você entrega as decisões, a prova de que elas funcionam e o código que as executa.

Seções obrigatórias do README:

- Visão geral: a solução em 1 a 2 parágrafos, incluindo como o sistema se comporta quando um provider cai
- Diagnóstico da v1: as quatro dores reproduzidas, com comando, resultado observado e causa no código
- Como rodar: subida, testes de caracterização e script de métrica, com os comandos exatos
- Métrica: a leitura dos três gráficos (o que saiu de onde, e por quê) e as exceções declaradas
- Tabela de capacidades: capacidade lógica, feature que a usa, modelo primário, fallback técnico, política com modelo fraco e número máximo de tentativas por destino
- Tabela de fallback: para cada feature, o que acontece quando não há modelo `large` disponível (qual resposta, qual status)
- Fluxos: para cada feature, o modo escolhido e como consumir o resultado, com o `curl` exato
- Troca de modelo: qual arquivo alterar, o que alterar e qual comando executar
- Roteiro de governança: os comandos que demonstram a recusa por orçamento e por limite de requisições
- Mapa de decisões: tabela com cada ADR, seu nível e uma linha de resumo

## Ordem de execução sugerida

**1.** Reconhecimento: suba o ambiente, leia o README do provider simulado, leia o código de `app/` e `edge/nginx.conf`, e chame as quatro tarefas nos modelos `large` e `mini` direto no provider.

**2.** Diagnóstico: reproduza as quatro dores do cenário com os modos de falha do provider e registre o que observou e onde está a causa.

**3.** Testes de caracterização contra a aplicação recebida. Marque a tag `v1-coupled`.

**4.** Escreva o script de métrica seguindo a régua do requisito 3 e meça a `v1`.

**5.** Escreva o plano, suba o gateway e faça o piloto em um componente. Meça, revise o plano.

**6.** Escale a refatoração com o agente, sempre com testes e métrica como juízes. Meça, marque a tag `v2-decoupled`.

**7.** Configure governança e resiliência no gateway e teste cada modo de falha do provider simulado.

**8.** Decida o fluxo de cada feature, implemente, atualize os testes na `main` e meça a versão final.

**9.** Escreva os ADRs e o README. Se um ADR descreve algo que você não consegue demonstrar pelo `/admin/calls` ou pela borda, ou o ADR ou o código estão errados.

**10.** Faça a verificação final do zero: num clone limpo do seu fork, suba o ambiente seguindo apenas o seu README e percorra os critérios de aceite item a item.

## Dicas finais

O `/admin/calls` é o seu melhor amigo. Toda afirmação sobre fallback, retry, troca de modelo ou orçamento pode ser conferida nele em segundos. Se você acha que o fallback funcionou mas o registro mostra uma única chamada ao provider primário, quem respondeu não foi quem você pensa.

A régua da métrica é fixa justamente para que ninguém ajuste a medida ao resultado. Se o seu script der, para a `v1`, números diferentes dos que a definição produz à mão para dois ou três módulos, o erro está no script. E não desenhe o código em função da fórmula (ex.: um import só para tirar um módulo da zona): a métrica aponta onde olhar, e o ADR precisa explicar por que a estrutura ficou melhor.

Streaming só funciona se nada no caminho acumular a resposta. Framework, middleware de compressão, gateway e proxy podem segurar os trechos e entregar tudo de uma vez no fim; se o `curl -N` pela borda mostrar o texto chegando em bloco, procure o buffer na sua própria cadeia, peça por peça.

Streaming e assíncrono resolvem problemas diferentes. Streaming muda a espera percebida, mas a conexão continua aberta; assíncrono libera a conexão, mas cobra estado e mais peças. Se uma escolha sua resolve o requisito de experiência por acidente, o ADR vai denunciar.

Fallback com modelo fraco não é um checkbox. Antes de ligar, olhe o que o `mini` devolve em cada tarefa. A pergunta do ADR não é "o gateway consegue fazer fallback?", é "uma resposta pior é melhor que nenhuma resposta, para quem consome esta feature?".

Uma boa entrega é enxuta: cada peça existe por causa de um requisito, e cada decisão tem nome, nível, motivo e prova.
