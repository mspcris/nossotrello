# Relatório mensal dos postos — automação "Entrega mensal" (recorrência)

Especificação para o NossoTrello (`tarefas.camim.com.br`) e para qualquer projeto
externo que monitore esses cards. Data: 09/09/2026.

---

## 1. Situação encontrada (produção, leitura)

Oito quadros de posto, todos com a coluna **"Relatórios Empresariais"** e os
mesmos 3 cards (um por tipo de relatório, todos "- Leonardo Pereira"):

| Board | Posto          | Coluna | Cards (CEDAE / Médicos PJ / CTRL-Q)     |
|------:|----------------|-------:|-----------------------------------------|
| 34    | ANCHIETA       | 343    | 2969 / 2971 / 2970  (coluna grafada "Reloatórios" — corrigir) |
| 35    | BANGU          | 348    | 2986 / 2984 / 2985                      |
| 36    | CAMPO GRANDE   | 346    | 2980 / 2978 / 2979                      |
| 37    | CAMPO GRANDE X | 345    | 2975 / 2977 / 2976                      |
| 38    | CAMPO GRANDE Y | 344    | 2974 / 2972 / 2973                      |
| 39    | NILÓPOLIS      | 317    | 2827 / 2965 / 2826                      |
| 40    | NOVA IGUAÇU    | 342    | 2968 / 2966 / 2967                      |
| 41    | REALENGO       | 347    | 2981 / 2983 / 2982                      |

Padrão observado nos dados: o gestor anexa o arquivo no card durante o mês e a
data de entrega do card aponta para o **dia 15 do mês seguinte** (ex.: anexo em
18/08 → entrega 15/09). O flag "Entregue" está marcado na maioria, sem uso real.

### 1.1 Quem são os gerentes — fonte: cadastro de Gestores do Hesk

O Tarefas não tem cargo no perfil. A fonte oficial é o **Hesk**
(`administrativo.camim.com.br`, Configurações → Gestores dos postos), tabelas
`dashboard_gestor`, `dashboard_gestorposto` e `dashboard_posto` no banco `hesk`
da **mesma RDS** (`postgres-db...us-east-1.rds.amazonaws.com:9432`, usuário
`camim_pg`) que o Tarefas já usa. É de lá que a página `/recursos/` e o
"meu-posto" do Hesk tiram a lista.

Casamento: **nome do quadro = nome do posto** (case-insensitive, sem acento):
`ANCHIETA` ↔ `Anchieta`, `CAMPO GRANDE X` ↔ `Campo Grande X`, etc.

```sql
-- gestores ativos por posto (rodar no banco hesk)
SELECT p.nome AS posto, g.nome, g.email, g.telefone
FROM dashboard_posto p
JOIN dashboard_gestorposto gp ON gp.posto_id = p.id
JOIN dashboard_gestor g ON g.id = gp.gestor_id
WHERE p.excluido_em IS NULL AND g.excluido_em IS NULL AND g.ativo
ORDER BY p.ordem, p.nome, g.nome;
```

Resultado hoje (09/09/2026) para os 8 quadros:

| Board | Posto (Hesk)   | Gestores cadastrados |
|------:|----------------|----------------------|
| 34    | Anchieta       | Elisangela Rodrigues <elisangela.rodrigues@clinicacamim.com.br>; Júlio Albuquerque <julio@camim.com.br> |
| 35    | Bangu          | Davi <davi@clinicacamim.com.br>; Renato <jose.renato@clinicacamim.com.br> |
| 36    | Campo Grande   | Luann <carne@camim.com.br>; Petterson <peterson@clinicacamim.com.br> |
| 37    | Campo Grande X | Alessandra Lourenço <alessandra@camim.com.br> |
| 38    | Campo Grande Y | Mariana Mello <marianamello@clinicacamim.com.br> |
| 39    | Nilópolis      | Romulo Azevedo <romulo@clinicacamim.com.br>; Thais Lima <thais@clinicacamim.com.br> |
| 40    | Nova Iguaçu    | Gabriel Carvalho <gabriel.carvalho@clinicacamim.com.br>; Marcos Dantas <dantas@clinicacamim.com.br> |
| 41    | Realengo       | Camilla Gaspar <gerenciar@camim.com.br>; Thiago Silva <thiago.silva@clinicacamim.com.br> |

Bate com quem de fato anexa nos cards (histórico), exceto Campo Grande Y, onde
quem anexa é raissa.reis@ e a gestora cadastrada é Mariana Mello — ambas são
membros do quadro; a cobrança vai para a gestora, como manda o cadastro.

Consequência de design: o Tarefas **lê o cadastro do Hesk em tempo real**
(alias de banco `hesk`, somente leitura, cache de 10 min) e mostra os gestores
na regra. A regra permite **adicionar** pessoas extras (multi-select de membros
do quadro), nunca substituir a fonte. Se o Hesk estiver fora, usa o último cache
e, no limite, avisa só o destinatário (Leonardo) com "gestores indisponíveis".

---

## 2. Conceito

Uma automação de coluna nova, do tipo **"Entrega mensal de relatório"**
(recorrência). Ela vale para todos os cards da coluna; cada card = um relatório.

Quando a regra existe na coluna, passa a existir no card um **espaço "Mensal"**
(aba no modal do card + chip no card do quadro) com o livro-razão de meses:
qual mês está pendente, quais foram entregues, com que arquivo, por quem, e o
parecer da IA.

Estado do card passa a significar sempre **"a próxima entrega"**:
`due_date = dia 15 do próximo ciclo pendente`, `is_delivered = False`.

### 2.1 Ciclo (competência)

- Ciclo `YYYY-MM` = **mês calendário**. Cada mês precisa de um anexo.
- Prazo (cobrança) = **dia 15 do próprio mês** (dia configurável na regra).
- Mês corrente = mês de hoje. Anexo depois do dia 15 conta para o mês (atrasado),
  nunca "pula" para o seguinte.
- **Meses passados sem anexo ficam PENDENTES e são cobrados** (ex.: parou em
  maio → junho, julho e agosto pendentes; setembro em aberto vencendo dia 15).

### 2.2 O que acontece ao anexar (gatilho `attach`)

1. **Mês de destino**: se o nome do arquivo cita um mês
   (`…_Abril_de_2026.pdf`, `CTRL-Q 08-2026.xlsx`, `2026-06`) e esse mês está em
   aberto, vai para ele; senão vai para o **mês pendente mais antigo** (≤ mês
   corrente). Sem nada pendente → arquivo **adicional** do mês citado/corrente,
   sem rolar a data. É isso que implementa "não pode cadastrar o mês seguinte
   com o anterior faltando".
2. Se `validar com IA` estiver ligado: extrai o texto (pdfplumber para PDF,
   openpyxl para XLSX, DOCX pelo XML, CSV/TXT direto; imagem/vídeo não valida) e
   chama a Groq (`GROQ_MODEL=openai/gpt-oss-120b`, já no `.env`) com título do
   card, posto, mês, instruções opcionais da regra e o texto (máx. 12k chars).
   Resposta JSON: `{"veredito": "aprovado|atencao|reprovado", "resumo", "problemas": []}`.
   Roda em thread: o upload responde na hora e a aba Mensal se atualiza sozinha.
3. Veredito:
   - `aprovado`, `atencao`, IA desligada, sem texto ou IA fora do ar → mês
     **entregue**; card: `is_delivered=False`,
     `due_date = dia 15 do próximo mês pendente` (cria o mês seguinte se não
     houver nenhum aberto); log no card.
   - `reprovado` (arquivo claramente errado) → mês **"anexo reprovado"**, card
     **não rola**; quem anexou recebe e-mail (e WhatsApp, se tiver) com cópia ao
     Leonardo. Um editor pode clicar **"Aceitar mesmo assim"** na aba Mensal.
4. E-mail ao destinatário da regra (`leonardo@camim.com.br`), assunto
   `[Tarefas] <posto> — <relatório> — <Mês/Ano> anexado`: quem anexou, quando,
   arquivo, veredito, resumo, pontos de atenção e link do card.

### 2.3 Cobrança (scheduler) — DIÁRIA

Comando `run_monthly_reports` no loop do `scheduler` do docker-compose (a cada
10 min, idempotente):

- Mês vencido (prazo dia 15 passou) sem anexo = **pendência**. Enquanto houver
  pendência, **todo dia, a partir das 8h**, sai **um e-mail por card** listando
  **todos os meses em atraso**, para os **gestores do posto** (cadastro do Hesk +
  extras da regra), citando o nome de cada gestor e o posto no corpo, **com
  cópia** ao destinatário (Leonardo). Um envio por dia por card (`reminded_at`).
  Assunto: `[Tarefas] <posto> — <relatório> — 3 meses sem relatório (Jun/2026, Jul/2026, Ago/2026)`
  ou `… — Set/2026 NÃO anexado`. Para de cobrar quando o último mês pendente
  recebe anexo.
- Sem gestor cadastrado no Hesk: o e-mail vai só para a cópia, com o aviso
  "nenhum gestor cadastrado para este posto".
- Reprocessa validações de IA presas (thread morta, Groq fora), até 3 tentativas;
  depois entrega sem validação com a nota "IA indisponível".
- Cria a linha do mês corrente se ainda não existir (o painel mostra
  "Pendente: Set/2026" mesmo sem ninguém abrir o card).

### 2.4 Nada de exclusão física

Anexo removido (soft-delete `is_active=False`) volta o ciclo para **pendente**
se ele era o único arquivo daquele ciclo; a data do card volta para o prazo do
ciclo. Linhas do livro-razão nunca são apagadas.

---

## 3. Modelo de dados (Django `boards`)

### 3.1 `ColumnAutomation` (existente) — novos valores

- `TRIGGER_CHOICES += ("attach", "Quando um anexo é adicionado a um card desta lista")`
  (gatilho genérico: também serve para "disparar e-mail", "etiqueta" etc.)
- `ACTION_CHOICES += ("monthly_report", "Entrega mensal de relatório (recorrência)")`
  — só aceito com `trigger="attach"`.
- `params` da ação:
  ```json
  {
    "day": 15,
    "recipient_email": "leonardo@camim.com.br",
    "extra_user_ids": [123, 456],       // pessoas ALÉM dos gestores do Hesk
    "posto_nome": "Anchieta",           // override opcional; default = nome do quadro
    "ai_validate": true,
    "ai_instructions": "texto livre opcional: o que o relatório precisa conter",
    "start_month": "2026-09"
  }
  ```

### 3.2 Tabela nova `boards_monthlyreportentry`

| Coluna            | Tipo                      | Descrição |
|-------------------|---------------------------|-----------|
| id                | bigint PK                 | |
| rule_id           | FK ColumnAutomation       | regra que gerou |
| card_id           | FK Card                   | |
| month             | date (dia 1)              | ciclo `YYYY-MM-01`; único por (card, month) |
| due_on            | date                      | prazo (dia 15 do mês) |
| status            | varchar(12)               | `pending` · `validating` · `delivered` · `rejected` · `skipped` (reservado) |
| attachment_id     | FK CardAttachment null    | arquivo principal do ciclo |
| extra_attachment_ids | jsonb                  | arquivos adicionais do mesmo mês (ids) |
| attached_at       | timestamptz null          | |
| attached_by_id    | FK User null              | |
| ai_status         | varchar(12)               | `off` · `pending` · `done` · `error` |
| ai_verdict        | varchar(12)               | `aprovado` · `atencao` · `reprovado` · `` |
| ai_summary        | text                      | resumo em PT-BR |
| ai_problems       | jsonb                     | lista de strings |
| ai_checked_at     | timestamptz null          | |
| ai_attempts       | smallint                  | tentativas (máx. 3) |
| notified_at       | timestamptz null          | e-mail "anexado" enviado |
| reminded_at       | timestamptz null          | última cobrança enviada (repete 1x/dia enquanto pendente) |
| accepted_by_id    | FK User null              | "Aceitar mesmo assim" |
| created_at / updated_at | timestamptz         | |

Índices: `(card, month)` unique; `(status, due_on)`.

---

## 4. Consulta para projetos externos (monitoramento)

Mesma RDS Postgres do Tarefas. Tudo o que o monitor precisa:

```sql
-- situação de cada card monitorado: o mês em aberto MAIS ANTIGO
-- (é nele que o próximo anexo entra); sem nada em aberto, o mês corrente
SELECT DISTINCT ON (c.id)
       b.id AS board_id, b.name AS posto, c.id AS card_id, c.title,
       e.month, e.due_on, e.status, e.attached_at, u.email AS attached_by,
       e.ai_verdict, e.ai_summary, e.reminded_at, e.notified_at
FROM boards_monthlyreportentry e
JOIN boards_card c     ON c.id = e.card_id
JOIN boards_column col ON col.id = c.column_id
JOIN boards_board b    ON b.id = col.board_id
LEFT JOIN auth_user u  ON u.id = e.attached_by_id
WHERE e.month <= date_trunc('month', current_date)::date
ORDER BY c.id,
         (e.status IN ('pending','rejected','validating')) DESC,
         CASE WHEN e.status IN ('pending','rejected','validating') THEN e.month END ASC,
         e.month DESC;

-- atrasados (prazo passou e continua pendente)
SELECT * FROM boards_monthlyreportentry
WHERE status = 'pending' AND due_on < current_date;
```

JSON somente-leitura para quem não acessa o banco:

```
GET https://tarefas.camim.com.br/api/monthly-reports/            (1 linha por card: mês em aberto mais antigo)
GET https://tarefas.camim.com.br/api/monthly-reports/?board=34   (só um quadro)
GET https://tarefas.camim.com.br/api/monthly-reports/?all=1      (todas as linhas do livro-razão)
Authorization: Token <NOSSOTRELLO_API_TOKEN>   (o mesmo token DRF que o Hesk já usa)
```

Resposta: `{"ok": true, "today": "2026-09-09", "count": 24, "rows": [{"board_id", "posto",
"card_id", "card_title", "month": "2026-06", "due_on", "status", "attached_at",
"attached_by", "attachment_id", "ai_verdict", "ai_summary", "reminded_at",
"notified_at", "card_url"}]}`.

---

## 5. Interface

1. **Modal "Automação" da coluna** (`column_automation_modal.html`): novo
   gatilho "Quando um anexo é adicionado…" e nova ação "Entrega mensal de
   relatório". Campos da ação: dia do prazo (15), e-mail do destinatário do
   resumo, responsáveis (checkboxes com os membros do quadro), validar com IA
   (sim/não) e instruções para a IA.
2. **Aba "📅 Mensal" no modal do card** (`card_modal_split.html`, só quando a
   coluna tem a regra ativa): lista de ciclos, do mais recente ao mais antigo,
   com estado, arquivo (link), quem/quando anexou, veredito e resumo da IA,
   botão "Aceitar mesmo assim" (só editor, só `rejected`). Topo em destaque:
   **"Pendente: Set/2026 — prazo 15/09"** ou **"Set/2026 entregue em 01/09 por
   Thaís"**.
3. **Chip no card do quadro** (template do card): `📎 falta Set/26` (âmbar; vermelho
   se prazo passou) ou `📎 Set/26 ok`. Sem animação nem piscar.
4. Aba **Anexos**: quando há regra, a linha de upload mostra "Este arquivo será
   o relatório de **Set/2026**" para ninguém anexar sem saber a que mês vai.

---

## 6. Rollout nos 8 quadros (comando `setup_monthly_reports`)

```
docker exec nossotrello-web-1 python manage.py setup_monthly_reports \
    --boards 34,35,36,37,38,39,40,41 --recipient leonardo@camim.com.br --remind-now
```

Idempotente. Para cada quadro:

1. Acha a coluna (aceita a grafia "Reloatórios") e corrige o nome para
   "Relatórios Empresariais".
2. Cria/reativa a regra `attach → monthly_report` com `day=15`,
   `recipient_email=leonardo@camim.com.br`, `ai_validate=true`. Responsáveis
   vêm do cadastro de Gestores do Hesk; nada fixo no código.
3. **Histórico** a partir dos anexos existentes (mês pelo nome do arquivo,
   senão pela data do upload; no máximo 12 meses para trás): mês com anexo →
   `delivered`; **mês sem anexo → `pending`** (será cobrado). `start_month` da
   regra = primeiro mês encontrado.
4. Card: `is_delivered=False`, `due_date = dia 15 do mês pendente mais antigo`
   (ou do mês seguinte, se tudo entregue). Log no card.
5. `--remind-now`: dispara na hora a cobrança dos meses já vencidos (um e-mail
   por card, gestores + cópia ao Leonardo). Setembro só é cobrado no dia 15.

## 7. Arquivos a tocar (NossoTrello)

| Arquivo | Mudança |
|---|---|
| `nossotrello/settings.py` | alias `DATABASES["hesk"]` (mesmo host/usuário, banco `hesk`) + router que proíbe migrate/write |
| `boards/services/hesk_gestores.py` (novo) | `gestores_do_posto(nome)` via SQL cru no alias `hesk`, cache 10 min |
| `boards/models.py` | choices novas em `ColumnAutomation`; model `MonthlyReportEntry` |
| `boards/migrations/0XXX_monthly_report.py` | tabela nova + índices |
| `boards/services/monthly_report.py` (novo) | ciclo, atribuição do anexo, IA (Groq), e-mails, lembrete do dia 15, aceitar, soft-delete |
| `boards/services/column_automation.py` | `run_for(card, "attach", column, actor, attachment=…)` roteando para o serviço |
| `boards/views/attachments.py` | chamar `run_for(..., "attach")` após criar o anexo (upload, colar print) e ao soft-deletar |
| `boards/views/column_automation.py` + `column_automation_modal.html` | gatilho/ação/params novos |
| `boards/views/cards.py` + `card_modal_split.html` | aba Mensal (contexto + partial `monthly_report_tab.html`) e ações `monthly_accept` |
| template do card no quadro | chip do ciclo |
| `boards/views/idcamim_api.py` (ou novo `monthly_api.py`) | `GET /api/monthly-reports/` |
| `boards/management/commands/run_monthly_reports.py` | scheduler (lembrete dia 15 + retry IA) |
| `boards/management/commands/setup_monthly_reports.py` | rollout/backfill dos 8 quadros |
| `docker-compose.yml` | adicionar `run_monthly_reports` no loop do `scheduler` |
| `requirements.txt` | `openpyxl` (XLSX) |
| `boards/management/commands/curate_whats_new.py` | entrada em Novidades |
| `boards/tests.py` | ciclo corrente, atribuição ao mês mais antigo, não rolar em `reprovado`, lembrete 1x |

---

## 8. Decisões assumidas (mudar aqui se discordar)

- "Validado" não bloqueia por `atencao`; só `reprovado` segura o ciclo, com
  override manual. Evita a IA travar entrega legítima.
- Pendência é cobrada TODO DIA (decisão do Cristiano em 09/09/2026), um e-mail
  por card agrupando os meses, a partir das 8h; o card fica vermelho de atraso
  e o chip mostra "falta".
- Anexo depois do dia 15 conta para o mês atrasado (mais antigo), nunca pula.
- Imagem/print não passa pela IA (o modelo gpt-oss-120b não lê imagem); entra
  como entregue com veredito vazio e o e-mail avisa "não validado".
- Excluir a regra no modal só a desativa (o livro-razão fica para auditoria).
- Histórico no rollout limitado a 12 meses para trás.
