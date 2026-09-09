# Relatório mensal dos postos — entrega e rollout (09/09/2026)

Complemento de [relatorio-mensal-automacao.md](relatorio-mensal-automacao.md).
Commits `924143a` (feature) e `c4608fb` (Novidades), deploy automático concluído.

## O que está no ar

- **Automação "Entrega mensal de relatório"** com gatilho novo "quando um anexo
  é adicionado". Cada card da lista precisa de um anexo por mês calendário. O
  anexo cai no mês pendente mais antigo, ou no mês citado no nome do arquivo
  (ex.: `…_Abril_de_2026.pdf`, `CTRL-Q 08-2026.xlsx`).
- **IA (Groq gpt-oss-120b)** lê PDF, XLSX, DOCX e texto. Aprovado ou atenção
  entrega o mês e manda o resumo ao Leonardo (`leonardo@camim.com.br`).
  Reprovado segura o mês, avisa quem anexou e o Leonardo, com botão "Aceitar
  mesmo assim" na aba Mensal. Imagem/print não passa pela IA.
- **Card** fica NÃO entregue com data de entrega no dia 15 do próximo mês
  pendente. Ganhou a aba "📅 Mensal" (histórico mês a mês: arquivo, quem/quando,
  parecer da IA) e um selo no quadro ("📎 falta Jun/2026").
- **Cobrança DIÁRIA** (ajuste do mesmo dia): enquanto houver mês vencido sem
  anexo, o scheduler (`run_monthly_reports`, a cada 10 min) manda todo dia a
  partir das 8h um e-mail por card listando todos os meses em atraso, citando o
  nome de cada gestor e o posto, com cópia ao Leonardo. Dia 15 é o prazo do mês
  corrente; para de cobrar quando o anexo entra.
- **Gerentes vêm do Hesk** (administrativo.camim.com.br → Configurações →
  Gestores dos postos), lidos pelo alias de banco `hesk`, somente leitura,
  casando nome do quadro = nome do posto. Nada fixo no código. Pessoas extras
  podem ser marcadas na regra (membros do quadro).
- **Ativar em outra lista**: raio ⚡ da lista → ação "Entrega mensal de
  relatório". Ao salvar, o histórico é montado a partir dos anexos existentes
  (até 12 meses para trás). Excluir a regra só a desativa.
- **Monitoramento externo**: `GET https://tarefas.camim.com.br/api/monthly-reports/`
  (`?board=34`, `?all=1`) com `Authorization: Token <NOSSOTRELLO_API_TOKEN>`;
  ou SQL na tabela `boards_monthlyreportentry` (ver spec).

## Rollout executado na VM

```
docker exec nossotrello-web-1 python manage.py setup_monthly_reports \
    --boards 34,35,36,37,38,39,40,41 --recipient leonardo@camim.com.br --remind-now
```

| Item | Resultado |
|---|---|
| Regras criadas | 8 quadros (34–41); coluna 343 do Anchieta corrigida para "Relatórios Empresariais" |
| Meses registrados | 170 (57 entregues pelo histórico, 113 pendentes) |
| Cobranças enviadas na hora | 24 cards, 89 meses em atraso (abril a agosto/2026) |
| Setembro/2026 | em aberto em todos os 24 cards; cobra sozinho no dia 15 |
| SMTP | confirmado com e-mail de teste (smtp.gmail.com, `tarefas@camim.com.br`) |

Destinatários resolvidos pelo Hesk no momento do rollout:

| Board | Posto | Gestores cobrados |
|------:|---|---|
| 34 | Anchieta | Elisangela Rodrigues, Júlio Albuquerque |
| 35 | Bangu | Davi, Renato |
| 36 | Campo Grande | Luann, Petterson |
| 37 | Campo Grande X | Alessandra Lourenço |
| 38 | Campo Grande Y | Mariana Mello |
| 39 | Nilópolis | Romulo Azevedo, Thais Lima |
| 40 | Nova Iguaçu | Gabriel Carvalho, Marcos Dantas |
| 41 | Realengo | Camilla Gaspar, Thiago Silva |

## Testes

20 testes novos (`boards/tests_monthly_report.py`) e a suíte existente passam
em SQLite descartável (módulo de settings no scratchpad; o `.env` local aponta
para a RDS de produção). Único item vermelho: erro de descoberta pré-existente
no pacote `boards/views` (import relativo em `activity.py`), sem relação.

## Atenção

A cobrança tratou como pendente todo mês sem anexo desde o primeiro relatório
de cada card. Se algum mês não era exigido, um editor anexa o arquivo daquele
mês (o nome do arquivo com o mês direciona) ou se marca manualmente.
