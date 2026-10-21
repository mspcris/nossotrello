# Escala dos médicos diretores clínicos — cobrança mensal nos postos de coleta (21/10/2026)

Complemento de [relatorio-mensal-automacao.md](relatorio-mensal-automacao.md) e
[relatorio-mensal-rollout-2026-09-09.md](relatorio-mensal-rollout-2026-09-09.md).
Commits `c85e0b2` (motor + comando) e `55146b0` (Novidades), deploy automático.

## Pedido (Cristiano, 21/10/2026)

Os postos com **posto de coleta** — Anchieta, Bangu, Campo Grande, Nova Iguaçu e
Realengo — precisam ter, cada um, uma coluna **DIRETORIA CLÍNICA** com o card
**ESCALA MÉDICOS DIRETORES CLÍNICOS**, cobrado todo mês como o relatório da CEDAE.
Decisões dele:

- cobrar de **Out/2026 em diante** (nada retroativo, nem em Anchieta, que tinha a
  escala de Jan/2026 anexada);
- a escala deve estar anexada **até o dia 1** do mês; "não anexou, pendente está";
- Campo Grande X (37) e Y (38) ficam de fora: são postos separados, sem posto de coleta;
- o resumo de cada anexo vai para `cristiano@camim.com.br` (a CEDAE é do Leonardo);
- a **carta de nomeação** do diretor clínico não entra nesse card — qualquer anexo
  no card vira a escala do mês pendente (e a IA reprova se for outro documento).
  Guardar a carta na coluna "DOCUMENTOS" do posto.

## O que mudou no código (`c85e0b2`)

1. **Anexo do mês seguinte** (`boards/services/monthly_report.py`): a escala é um
   relatório prospectivo — a de novembro é anexada em outubro. Se o nome do
   arquivo cita o mês seguinte ao corrente (com ou sem ano: `Escala_Novembro.pdf`
   em outubro), o arquivo entra nesse mês; o que estiver pendente continua
   pendente e cobrado. Sem mês no nome, vale a regra antiga (pendente mais
   antigo; se nada pendente, adicional do mês corrente). Virada de ano coberta
   (`Janeiro` em dezembro = janeiro do ano seguinte).
2. **`setup_monthly_reports`**: flags `--start-month YYYY-MM` (cobra deste mês em
   diante; sem ela, desde o 1º anexo achado) e `--ai-instructions`. Com
   `--column`, só casa a coluna **exata** — antes caía na heurística "relat+empresar"
   e alterava a regra de "Relatórios Empresariais" (teste cobre).
3. **E-mail de cobrança** cita quem de fato recebe o resumo (nome do usuário pelo
   e-mail da regra) em vez de "Leonardo Pereira" fixo, e o exemplo de nome de
   arquivo usa o título do card.
4. Teste antigo do comando (`test_setup_command_creates_rule_fixes_name_and_reminds`)
   usava o relógio real em `--remind-now` e passou a falhar ao virar o mês; fixado
   no dia patchado.

## Rollout executado na VM (21/10/2026, 16:34)

Script idempotente no container (coluna roxa no fim do quadro + card criado por
Cristiano, log no card, versão do quadro bumpada):

| Board | Posto        | Coluna DIRETORIA CLÍNICA | Card  |
|------:|--------------|-------------------------:|------:|
| 34    | ANCHIETA     | 130 (já existia)         | 439 (já existia) |
| 35    | BANGU        | 1281                     | 22099 |
| 36    | CAMPO GRANDE | 1282                     | 22100 |
| 40    | NOVA IGUAÇU  | 1283                     | 22101 |
| 41    | REALENGO     | 1284                     | 22102 |

Regra (dry-run conferido antes):

```
docker exec nossotrello-web-1 python manage.py setup_monthly_reports \
    --boards 34,35,36,40,41 --column "DIRETORIA CLÍNICA" --day 1 --start-month 2026-10 \
    --recipient cristiano@camim.com.br \
    --ai-instructions "Escala mensal de plantão dos médicos diretores clínicos do posto de coleta (cobertura 24h, um médico por dia). Precisa trazer o nome do posto, o mês e ano de referência, os médicos com CRM e cargo de Diretor Clínico e a marcação dos dias de plantão de cada um no mês. Reprove se for outro documento (ex.: carta de nomeação, escala de outro posto ou de outro mês)." \
    --remind-now
```

Resultado: regras 40–44 (uma por coluna), `Out/2026` pendente com prazo
01/10/2026 nos 5 cards, 5 cobranças enviadas na hora aos gestores do Hesk
(Anchieta: Elisangela Rodrigues e Júlio Albuquerque; Bangu: Davi e Renato; Campo
Grande: Luann e Petterson; Nova Iguaçu: Gabriel Carvalho e Marcos Dantas;
Realengo: Camilla Gaspar e Thiago Silva). As 8 regras da CEDAE/Médicos PJ/CTRL-Q
continuam com dia 15, Leonardo e `start 2026-09`.

## Como funciona daqui em diante

- Todo dia a partir das 8h, enquanto Out/2026 (ou qualquer mês vencido) estiver
  sem escala, sai um e-mail por card aos gestores. Para quando o anexo entra.
- Ao anexar: IA valida (mês, posto, médicos/CRM, plantões). Reprovado segura o mês
  com "Aceitar mesmo assim"; aprovado/atenção entrega e o resumo vai ao Cristiano.
- Entregue o mês corrente, a linha do mês seguinte abre com prazo dia 1. A escala
  do mês seguinte pode ser anexada antes, pela aba Mensal (linha do mês) ou pela
  aba Anexos com o mês no nome do arquivo.
- Admin do quadro pode "Liberar" um mês (dispensa, `b929dcc`).

## Para incluir outro posto

Criar a coluna "DIRETORIA CLÍNICA" com o card e rodar o mesmo comando com o id
do quadro (`--boards N`), ou ligar pelo raio ⚡ da coluna escolhendo "Entrega
mensal de relatório" (dia 1, destinatário, instruções da IA).
