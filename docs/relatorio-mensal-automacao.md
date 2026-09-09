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

- Ciclo `YYYY-MM` = entrega com prazo **dia 15 de YYYY-MM** (dia configurável, default 15).
- Janela de anexo do ciclo M: `16/(M-1)` até `15/M`.
- Ciclo corrente: se hoje ≤ dia 15 → mês atual; senão → mês seguinte.
  Ex.: 09/09 → ciclo Set/2026 (prazo 15/09). 20/09 → ciclo Out/2026 (prazo 15/10).

### 2.2 O que acontece ao anexar (gatilho `attach`)

1. O anexo é atribuído ao **ciclo pendente mais antigo** entre `início da regra` e
   o `ciclo corrente`. Se não há ciclo pendente (o corrente já foi entregue), o
   arquivo entra como **arquivo adicional** do ciclo corrente, sem rolar a data.
   → Isso implementa "não pode cadastrar o mês seguinte com o anterior faltando".
2. Se `validar com IA` estiver ligado: extrai o texto (pdfplumber para PDF,
   openpyxl para XLSX, texto puro para CSV/TXT; imagem não é validada) e chama
   a Groq (`GROQ_MODEL=openai/gpt-oss-120b`, já configurado no `.env`) com o
   prompt: título do card, posto, mês de referência, instruções opcionais da
   regra, e o texto extraído (máx. ~12k caracteres). Resposta em JSON:
   `{"veredito": "aprovado|atencao|reprovado", "resumo": "...", "problemas": ["..."]}`.
3. Veredito:
   - `aprovado` ou `atencao` (ou IA desligada/indisponível) → ciclo fica **entregue**,
     card: `is_delivered=False`, `due_date = dia 15 do ciclo seguinte`, log no card.
   - `reprovado` (arquivo claramente errado) → ciclo fica **"anexo reprovado"**,
     card **não rola**; quem anexou recebe aviso (WhatsApp/e-mail) e o Leonardo
     também. Um editor pode clicar **"Aceitar mesmo assim"** na aba Mensal.
4. E-mail para o destinatário da regra (`leonardo@camim.com.br`), assunto
   `[Tarefas] <posto> — <relatório> — <Mês/Ano> anexado`, corpo: quem anexou,
   quando, nome do arquivo, veredito, resumo da IA, problemas, link do card.

### 2.3 Dia 15 (scheduler)

Comando `run_monthly_reports` entra no loop do `scheduler` do docker-compose
(a cada 10 min, idempotente):

- No dia do prazo (15), para cada ciclo corrente **pendente**: e-mail aos
  responsáveis da regra **com cópia** para o destinatário (Leonardo), assunto
  `[Tarefas] <posto> — <relatório> — <Mês/Ano> NÃO anexado`, link do card.
  Grava `reminded_at` (manda 1 vez por ciclo).
- Também reprocessa validações de IA que falharam (`ai_status=pending`), com
  limite de tentativas.
- Cria a linha do ciclo corrente se ainda não existir (para o painel mostrar
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
| status            | varchar(12)               | `pending` · `delivered` · `rejected` · `skipped` (histórico sem anexo, antes do início da regra) |
| attachment_id     | FK CardAttachment null    | arquivo principal do ciclo |
| attached_at       | timestamptz null          | |
| attached_by_id    | FK User null              | |
| ai_status         | varchar(12)               | `off` · `pending` · `done` · `error` |
| ai_verdict        | varchar(12)               | `aprovado` · `atencao` · `reprovado` · `` |
| ai_summary        | text                      | resumo em PT-BR |
| ai_problems       | jsonb                     | lista de strings |
| ai_checked_at     | timestamptz null          | |
| notified_at       | timestamptz null          | e-mail "anexado" enviado |
| reminded_at       | timestamptz null          | e-mail "NÃO anexado" (dia 15) enviado |
| accepted_by_id    | FK User null              | "Aceitar mesmo assim" |
| created_at / updated_at | timestamptz         | |

Índices: `(card, month)` unique; `(status, due_on)`.

---

## 4. Consulta para projetos externos (monitoramento)

Mesma RDS Postgres do Tarefas. Tudo o que o monitor precisa:

```sql
-- situação atual de cada card monitorado (1 linha por card = ciclo corrente)
SELECT b.id AS board_id, b.name AS posto, c.id AS card_id, c.title,
       e.month, e.due_on, e.status, e.attached_at, u.email AS attached_by,
       e.ai_verdict, e.ai_summary, e.reminded_at, e.notified_at
FROM boards_monthlyreportentry e
JOIN boards_card c     ON c.id = e.card_id
JOIN boards_column col ON col.id = c.column_id
JOIN boards_board b    ON b.id = col.board_id
LEFT JOIN auth_user u  ON u.id = e.attached_by_id
WHERE e.month = date_trunc('month',
        CASE WHEN extract(day FROM current_date) <= 15
             THEN current_date ELSE current_date + interval '1 month' END)::date
ORDER BY b.name, c.title;

-- atrasados (prazo passou e continua pendente)
SELECT * FROM boards_monthlyreportentry
WHERE status = 'pending' AND due_on < current_date;
```

Também haverá um JSON somente-leitura para quem não acessa o banco:
`GET /api/monthly-reports/?board=34` (ou sem filtro), autenticado com a mesma
`X-Admin-Key` dos demais endpoints administrativos do Tarefas. Retorna a mesma
projeção da primeira query, agrupada por board.

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

Executa uma vez, idempotente, na VM (`nossotrello-web-1`):

1. Renomeia a coluna 343 para "Relatórios Empresariais".
2. Cria em cada coluna (343, 348, 346, 345, 344, 317, 342, 347) a regra
   `attach → monthly_report` com `day=15`, `recipient_email=leonardo@camim.com.br`,
   `ai_validate=true`, `start_month=2026-09`. Responsáveis vêm do cadastro de
   Gestores do Hesk (tabela 1.1); nada fixo no código.
3. **Histórico**: para cada card, percorre os anexos ativos desde março/2026 e
   cria as linhas dos ciclos passados: com anexo na janela → `delivered`
   (`attached_at/by` do anexo, sem IA, sem e-mail); sem anexo → `skipped`.
   Histórico é só informativo: não gera cobrança nem bloqueio.
4. **Ciclo corrente (Set/2026, prazo 15/09)** — regra do Cristiano "se já
   anexou neste mês, deixa pendente para o próximo dia 15":
   - anexo ativo entre 16/08 e 15/09 → ciclo `delivered`, card
     `is_delivered=False`, `due_date=2026-10-15`;
   - sem anexo nessa janela → ciclo `pending`, card `is_delivered=False`,
     `due_date=2026-09-15`.
   Com os dados de hoje só entram como entregues: board 36 (CTRL-Q e CEDAE,
   anexos 18/08) e board 39 (CEDAE, 01/09). Os outros 21 cards ficam pendentes
   para 15/09 e recebem a cobrança no dia 15.
5. Registra no CardLog de cada card: "Automação de entrega mensal ativada;
   ciclo Set/2026 pendente/entregue".

---

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
- Um único aviso no dia 15; sem repetição diária (o card fica vermelho de atraso
  e o chip mostra "falta").
- Anexo depois do dia 15 conta para o ciclo atrasado (mais antigo), nunca pula.
- Imagem/print não passa pela IA (o modelo gpt-oss-120b não lê imagem); entra
  como entregue com veredito vazio e o e-mail avisa "não validado (imagem)".
- Regra só enforça a partir de `start_month`; meses anteriores viram histórico.
