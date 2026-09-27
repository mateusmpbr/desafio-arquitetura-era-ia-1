# 0007. Ler a Main Sequence com duas exceções declaradas: `schemas` e `config`

- Status: aceita
- Data: 2026-09-26
- Nível: software

## Contexto

A métrica (`metrics/coupling.py`, régua do requisito 3) mede cada módulo de `app/helpdesk/`. Resultados versionados em `metrics/results/`:

| Componente | v1-coupled (Ca/Ce/I/A/D) | v2-decoupled | main |
|---|---|---|---|
| `llm` | 4 / 1 / 0,20 / 0,00 / **0,80** | removido | removido |
| `config` | 6 / 0 / 0,00 / 0,00 / **1,00** | 2 / 0 / 0,00 / 0,00 / **1,00** | 2 / 0 / 0,00 / 0,00 / **1,00** |
| `schemas` | 5 / 0 / 0,00 / 0,00 / **1,00** | 5 / 0 / 0,00 / 0,00 / **1,00** | 7 / 0 / 0,00 / 0,00 / **1,00** |
| `ports` | n/a | 5 / 0 / 0,00 / 1,00 / 0,00 | 7 / 1 / 0,13 / 0,67 / 0,21 |
| `adapters.gateway` | n/a | 1 / 1 / 0,50 / 0,00 / 0,50 | 1 / 1 / 0,50 / 0,00 / 0,50 |
| `adapters.job_store` | n/a | n/a | 1 / 2 / 0,67 / 0,00 / 0,33 |
| `classification`, `extraction`, `suggestion` | 1 / 3 / 0,75 / 0,00 / 0,25 | 1 / 2 / 0,67 / 0,00 / 0,33 | 1 / 2 / 0,67 / 0,00 / 0,33 |
| `report` | 1 / 4 / 0,80 / 0,00 / 0,20 | 1 / 2 / 0,67 / 0,00 / 0,33 | 1 / 2 / 0,67 / 0,00 / 0,33 |
| `tickets` | 1 / 1 / 0,50 / 0,00 / 0,50 | igual | igual |
| `main` | 0 / 5 / 1,00 / 0,00 / 0,00 | 0 / 8 / 1,00 / 0,00 / 0,00 | 0 / 10 / 1,00 / 0,00 / 0,00 |

Zona de dor: A < 0,5, I < 0,5 e D ≥ 0,5 ao mesmo tempo.

## Opções consideradas

1. Tratar todo componente na zona de dor como problema e mudar o código até sair (inclusive com imports que não expressam dependência real).
2. Declarar como estáveis por natureza os componentes que a fórmula põe na zona sem que haja um problema real, justificando cada um, e cobrar a métrica dos outros.

## Decisão

Opção 2. Estáveis por natureza na `main`:

- **`schemas`**: tipos de valor do contrato HTTP e do domínio (`TicketInput`, `Classification`, `OrderData`, `PeriodInput`, `Topic`, `TopicsReport`, `JobState`, `ReportJob`). São modelos pydantic sem comportamento, e só mudam quando o contrato das features muda, algo que o desafio fixa. Estáveis por definição (muitos dependem deles), concretos por natureza (um tipo de valor não tem o que abstrair). Ca alto é o esperado aqui, não um sintoma.
- **`config`**: na v1, era o componente mais perigoso da aplicação (Ca = 6), porque guardava o que mais muda: nomes físicos, base URLs e chaves de provider. Tudo isso foi para o gateway (ADR 0002, 0003). O que sobrou é uma declaração de valores sem comportamento: endereço e chave do gateway (lidos do ambiente), nomes lógicos das capacidades, timeouts e parâmetros do relatório. Só `main` (ponto de composição) e `tickets` o leem. As features recebem os valores por construtor. Trocar modelo ou provider não toca mais nele (a seção "Troca de modelo" do README não passa por `app/`).

Não são exceção, e não precisam ser: `adapters.gateway` (o componente que chama o gateway) e as quatro features estão fora da zona.

Leitura da evolução:

- **v1 → v2**: saiu da zona o componente que era o problema de verdade, `llm`, concreto e com as quatro features penduradas nele. No lugar dele entrou `ports`, que nasce sobre a Main Sequence (A = 1, I = 0). As features ficaram um pouco mais longe (D de 0,25 para 0,33), e está certo: trocaram dois concretos (`config`, `llm`) por um abstrato. O que importa é para onde as setas apontam, não o D de cada ponto isolado. `config` perdeu 4 dependentes (Ca de 6 para 2).
- **v2 → main**: `ports` ganhou o erro `CapabilityUnavailable` (classe concreta) e o port `JobStore`, e passou a importar `schemas` para tipar `ReportJob`: A = 0,67, I = 0,13, D = 0,21, ainda perto da sequência. O novo `adapters.job_store` fica junto das features (I = 0,67). `main` continua como o único componente que conhece os adaptadores concretos.
- **`adapters.gateway` em D = 0,50**: está na fronteira, mas fora da zona (I = 0,50, não < 0,5). O piloto mostrou que, implementado só por tipagem estrutural, ele ficaria em D = 1,00 (Revisão 1 do plano de refatoração). A herança explícita de `CompletionGateway` não é um import para agradar a fórmula: é a seta da inversão de dependência (o detalhe depende da abstração). Na `main`, o adaptador ainda usa `CapabilityUnavailable` do port para traduzir os erros do SDK.

## Consequências

- Melhor: a métrica aponta onde olhar, e cada exceção tem motivo escrito. Um componente novo na zona de dor precisa de justificativa aqui ou de mudança de estrutura.
- Pior: as exceções pedem disciplina. Se alguém voltar a pôr nome de modelo ou chave em `config`, a fórmula não acusa nada de novo, porque ele já está na zona. A proteção nesse caso são os `grep` do README e os testes, não a métrica.

## Evidência

```
.venv/bin/python metrics/coupling.py app/helpdesk --name main
git worktree add ../v1 v1-coupled && .venv/bin/python metrics/coupling.py ../v1/app/helpdesk --name v1-coupled
git diff --exit-code metrics/results/v1-coupled.csv     # reproduz o CSV versionado
```

Na `main`, os únicos componentes marcados `<- zona de dor` na saída do script são `config` e `schemas`.
