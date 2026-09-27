# 0004. Decidir o modo de execução de cada feature pelas características do contrato

- Status: aceita
- Data: 2026-09-26
- Nível: solução

## Contexto

Na v1 as quatro features respondem de forma síncrona. Medido pela borda (diagnóstico): F1 1,2 s, F4 1,2 s, F2 17,6 s com o primeiro byte junto do último, F3 do mês com `504` em 32,8 s e a aplicação ainda trabalhando por mais 5 minutos. A borda encerra com `504` qualquer requisição que passe 30 s sem enviar um byte. Os requisitos de experiência são: F1 em até 3 s; primeiro trecho da F2 em até 1,5 s; F3 aceita em até 1 s e o relatório disponível depois; nenhum `504`.

A árvore de decisão usada em cada feature: **alguém está esperando agora?** → **cabe no orçamento de latência?** → **é consumível aos poucos?**

## Opções consideradas

Para cada feature: síncrono (com timeout explícito), streaming (SSE) ou Asynchronous Request-Reply (`202` + polling).

## Decisão

### F1 Classificar ticket: síncrono

- Alguém está esperando agora? Sim: o cliente, na tela de abertura do ticket, esperando a confirmação.
- Cabe no orçamento de latência? Sim. A saída tem cerca de 13 tokens: 0,8 s até o primeiro token mais 0,3 s de geração, 1,1 s medido pela borda contra 3 s exigidos.
- É consumível aos poucos? Não. A saída é curta e de valores fixos (`category`, `priority`); meio JSON não serve para nada.

Síncrono, com timeout explícito em duas camadas. No gateway, 4 s por destino (primário, fallback técnico, modelo fraco). Na aplicação, 12 s para a chamada inteira (`INTERACTIVE_TIMEOUT_S`). Se nada responder, a F1 devolve `503` com o motivo, antes dos 15 s exigidos e bem antes da borda. Streaming seria custo sem ganho, e assíncrono obrigaria o cliente a fazer polling por 1 s de trabalho.

### F2 Sugerir resposta: streaming (SSE)

- Alguém está esperando agora? Sim: o atendente, olhando a tela.
- Cabe no orçamento de latência? Não. A saída tem cerca de 613 tokens a 40 tokens/s: 16 s de geração, contra 1,5 s até o primeiro trecho, e a menos de 15 s do `504` da borda.
- É consumível aos poucos? Sim. O atendente começa a ler e editar assim que o texto aparece.

Streaming por SSE: `Content-Type: text/event-stream`, um evento `data: {"chunk": ...}` por trecho, `event: end` no fim e `event: error` se a geração cair depois do `200` (formato de Contratos sugeridos). Assíncrono resolveria a borda, mas não a experiência: o atendente continuaria sem ver nada até o fim, e ainda faria polling. Streaming muda a espera percebida (primeiro trecho em 0,8 s), e a borda nunca vê 30 s de silêncio, porque há bytes a cada ~25 ms.

Detalhes que fazem o streaming funcionar de ponta a ponta:

- A aplicação espera o primeiro trecho antes de enviar o `200`. Se nenhum destino atender (todos os fallbacks esgotados antes de gerar texto), o cliente recebe um `503` com status HTTP de verdade. Depois do primeiro trecho, qualquer falha vira `event: error`.
- Header `X-Accel-Buffering: no`: sem ele, o nginx da borda acumula a resposta (`proxy_buffering` ligado por padrão) e entrega tudo em bloco.
- O gateway recebe `stream: true` e repassa os trechos sem acumular. O LiteLLM só tenta fallback no meio do stream se ainda não saiu nenhum conteúdo. Depois disso ele repassa o erro, e o adaptador o transforma em `CapabilityUnavailable`.

### F3 Relatório de temas: Asynchronous Request-Reply

- Alguém está esperando agora? Não. Quem pede é um painel interno, e ninguém fica olhando para ele.
- Cabe no orçamento de latência? Não. São 5.000 tickets em 34 lotes de 150 (o mês não cabe na janela de 8.000 tokens), de 9 a 12 s por lote: cerca de 6 min em série. Mesmo em paralelo, fica perto dos 30 s da borda, e os 1 s exigidos para aceitar o pedido estão fora de alcance de qualquer modo síncrono.
- É consumível aos poucos? Não. Os temas e as contagens só fecham quando todos os lotes terminam. O painel não expõe callback, então a entrega tem que ser por polling.

Asynchronous Request-Reply: `POST /reports/topics` responde `202` com `Location: /reports/topics/status/{id}` e `Retry-After: 5`. A URL de status responde `200` com `pending`/`running` (com `progress: "n/5000"`) ou `failed` (com `reason`), e `303 See Other` para `/reports/topics/{id}` quando a tarefa chega a `done`. Streaming não serve: manteria a conexão aberta por minutos para entregar um resultado que não é consumível aos poucos.

Como a tarefa roda:

- Os lotes vão em paralelo, até 12 ao mesmo tempo (`REPORT_CONCURRENCY`). O mês leva cerca de 30 s em vez de 6 min. São 34 chamadas, cabem no limite de 600 req/min da chave.
- A agregação acontece na ordem dos lotes, como na versão síncrona: o resultado é idêntico ao da v1 (a caracterização compara com o golden).
- Falha rápida: o primeiro lote que falha leva a tarefa a `failed` e cancela os lotes que ainda não começaram. Com os dois providers em `error_500`, a tarefa falha em cerca de 7 s. Cada lote tem teto de 50 s na aplicação (`REPORT_CALL_TIMEOUT_S`), acima do pior caso do gateway (18 + 18 + 8 s). Com os providers travados, a falha chega em cerca de 44 s: sempre antes dos 60 s, e nunca presa em `running`.
- Estado em memória, atrás do port `JobStore` (adaptador `InMemoryJobStore`). Sobreviver a reinício está fora de escopo, e uma fila com worker seriam mais dois serviços para justificar sem requisito que peça. Persistir passa a ser trocar o adaptador no ponto de composição.

### F4 Extrair dados do pedido: síncrono

- Alguém está esperando agora? Sim: a automação de troca e devolução espera o resultado para seguir.
- Cabe no orçamento de latência? Sim. A saída tem cerca de 11 tokens, 1,2 s medido pela borda.
- É consumível aos poucos? Não. Um JSON de dois campos alimenta uma máquina, e meio resultado é inútil (ou perigoso).

Síncrono, com os mesmos timeouts da F1 (4 s por destino no gateway, 12 s na aplicação). Sem modelo fraco (ADR 0005): se os dois `large` caírem, a F4 responde `503` explícito em cerca de 4 s, e a automação sabe que precisa tentar de novo ou escalar.

## Consequências

- Melhor: nenhuma feature depende mais da paciência da borda. Os quatro requisitos de experiência são medidos em `tests/acceptance/test_flows.py`.
- Pior: o contrato de F2 e F3 mudou, e os clientes precisam consumir SSE ou fazer polling. O estado da F3 some se a aplicação reiniciar. Quando uma tarefa falha rápido, os até 12 lotes que já estavam em andamento continuam no gateway até os timeouts dele. O custo desse "desistir não é cancelar" residual é limitado, ao contrário da v1, onde eram 34 lotes sem limite.
- A vigiar: a concorrência da F3 contra o limite de requisições da chave `helpdesk-app`. Um mês com mais tickets aumenta o número de lotes, não a duração de cada um.

## Evidência

Medido pela borda, provider em modo normal (`tests/acceptance/test_flows.py`):

- F1: `200` em 1,09 s.
- F2: primeiro trecho em 0,81 s, total de 16,1 s, 607 eventos, último `event: end`.
- F3 do mês: `202` em 21 ms, `303` depois de 30,1 s, `total_tickets: 5000`, 34 chamadas `topics` no `/admin/calls`.
- F2 com `claude-fake-large` em `midstream_error`: `200`, 151 trechos e depois `event: error` / `data: {"ticket_id": "TK-00042", "message": "A geração foi interrompida"}`.
- F3 com os dois providers em `error_500`: `{"state": "failed", "reason": "Modelo indisponível para o relatório: ..."}` em 7,0 s.
