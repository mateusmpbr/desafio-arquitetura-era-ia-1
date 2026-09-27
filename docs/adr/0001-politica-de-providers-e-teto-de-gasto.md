# 0001. Aceitar dois providers de IA e fixar um teto mensal de gasto por aplicação

- Status: aceita
- Data: 2026-09-26
- Nível: corporativa

## Contexto

- Na última instabilidade de um provider, metade do helpdesk parou junto (Dor 3 do diagnóstico). F1 e F4 dependiam só da OpenAI; F2 e F3, só da Anthropic.
- O relatório do mês que ninguém recebeu custou US$ 0,85 em tokens (34 chamadas depois do `504`, medidas no `/admin/calls`). Ninguém tinha visibilidade nem limite sobre esse gasto: as chaves dos providers estavam na aplicação.
- Estimativa de consumo com o volume de agosto (5.000 tickets), preços do README do provider e tokens medidos no `/admin/calls`:
  - classificação: 34 tokens de entrada × US$ 2,50/M + 13 de saída × US$ 10/M ≈ US$ 0,0002 por ticket
  - extração: ≈ US$ 0,0002 por ticket
  - sugestão: 40 × US$ 3/M + 613 × US$ 15/M ≈ US$ 0,0093 por ticket
  - relatório do mês: ≈ US$ 0,85 por pedido; 4 pedidos por mês ≈ US$ 3,40
  - total: 5.000 × US$ 0,0097 + US$ 3,40 ≈ US$ 52 por mês

## Opções consideradas

1. Um provider único homologado, escolhido por preço.
2. Dois providers homologados, com modelos equivalentes nos dois, e cada aplicação com um teto de gasto mensal aplicado na infraestrutura.
3. Qualquer provider, escolhido por feature pelo time ("o que funcionou melhor no teste"), sem teto.

## Decisão

Opção 2.

- Providers aceitos: OpenAI e Anthropic. Toda capacidade de IA precisa ter destino equivalente nos dois, para que a queda de um não pare o atendimento. Um terceiro provider entra só por uma nova decisão neste nível.
- Credenciais dos providers pertencem à plataforma (o gateway, ADR 0002), nunca às aplicações.
- Teto do helpdesk: US$ 100 a cada 30 dias, cerca de 2× a estimativa acima. A folga cobre pedidos repetidos de relatório e sugestões regeneradas. O teto é aplicado como orçamento da chave `helpdesk-app` no gateway (ADR 0006): estourou, o gateway recusa. Rever o teto é decisão deste nível, não do time da aplicação.

## Consequências

- Melhor: nenhuma queda isolada de provider para uma feature. O gasto tem dono e limite, e um processo que escapa (como o relatório órfão da v1) não pode passar do teto.
- Pior: dois contratos e duas contas para manter. Quando o teto estoura, as features de IA falham de forma explícita (`503`) até o próximo ciclo ou até o teto ser revisto.
- A vigiar: o gasto da chave `helpdesk-app` (`GET /key/info` no gateway) contra o teto. Se o volume de tickets crescer, a estimativa acima precisa ser refeita.

## Evidência

- `gateway/config.yaml`: todo `model_name` primário tem um grupo `-alt` no outro provider.
- `gateway/keys.json`: `helpdesk-app` com `"max_budget": 100, "budget_duration": "30d"`.
- `curl -s localhost:4000/key/info?key=sk-helpdesk-app-0001 -H "Authorization: Bearer sk-gateway-master-0001"` mostra `max_budget` e `spend`.
