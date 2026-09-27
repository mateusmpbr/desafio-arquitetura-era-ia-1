# 0003. Expor à aplicação capacidades lógicas por feature, mapeadas para modelos físicos no gateway

- Status: aceita
- Data: 2026-09-26
- Nível: solução

## Contexto

Na v1, o nome do modelo físico estava no código (`config.CLASSIFICATION_MODEL = "gpt-fake-large"`), e trocar custou rebuild e restart da aplicação (Dor 4). As features também não têm os mesmos requisitos: o `mini` serve para umas e não para outras (ADR 0005), e os timeouts toleráveis vão de 4 s (classificação) a 18 s (lote do relatório). Um nome lógico genérico ("large", "fast") compartilhado entre features obrigaria todas a aceitar a mesma política.

## Opções consideradas

1. Nomes por tamanho ou qualidade (`smart`, `fast`), compartilhados pelas features.
2. Um nome lógico por feature (capacidade), com a política de destinos de cada uma no gateway.
3. Manter o nome físico na aplicação e só trocar o endereço para o gateway.

## Decisão

Opção 2. A aplicação conhece quatro nomes, um por feature, definidos em `app/helpdesk/config.py` e injetados em cada feature pelo ponto de composição:

| Capacidade (nome lógico) | Feature | Primário | Fallback técnico (`-alt`) | Modelo fraco (`-weak`) |
|---|---|---|---|---|
| `ticket-classification` | F1 | `openai/gpt-fake-large` | `anthropic/claude-fake-large` | `openai/gpt-fake-mini` |
| `reply-suggestion` | F2 | `anthropic/claude-fake-large` | `openai/gpt-fake-large` | `anthropic/claude-fake-mini` |
| `topics-report` | F3 | `anthropic/claude-fake-large` | `openai/gpt-fake-large` | `anthropic/claude-fake-mini` |
| `order-extraction` | F4 | `openai/gpt-fake-large` | `anthropic/claude-fake-large` | nenhum (falha explícita) |

- Os primários são os mesmos da v1: os dois `large` são equivalentes e dão a mesma saída (a suíte de caracterização passa igual).
- Convenção: `<capacidade>` é o grupo que a aplicação chama; `<capacidade>-alt` e `<capacidade>-weak` são grupos internos, usados só como destino de fallback. A chave `helpdesk-app` só tem acesso aos quatro nomes primários. Chamar `ticket-classification-weak` com ela devolve `key not allowed to access model`.
- Os destinos físicos estão declarados uma vez (âncoras YAML `x-openai-large` etc., com base URL, chave e preço). Cada capacidade só escolhe o destino e o timeout.

## Consequências

- Melhor: trocar o modelo de uma feature é mudar uma linha em `gateway/config.yaml` e rodar `docker compose restart gateway`. A troca de uma feature não afeta as outras.
- Pior: 11 entradas em `model_list` em vez de 4. Uma feature nova exige capacidade nova no gateway e na lista de modelos da chave.
- A vigiar: o nome lógico é contrato entre aplicação e plataforma. Renomear exige mudar os dois lados.

## Evidência

Troca feita durante o desenvolvimento: `ticket-classification` passou de `*openai-large` para `*openai-mini`, seguido de `docker compose restart gateway`. O gateway ficou saudável em 16 s. A chamada seguinte à F1 apareceu no `/admin/calls` como `"model": "gpt-fake-mini"`, e o `StartedAt` do container `app` não mudou (`02:00:50` antes e depois). O passo a passo está na seção "Troca de modelo" do README.
