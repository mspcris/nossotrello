# NossoTrello — Notas para Claude

App Django em `tarefas.camim.com.br`. Login via IDCamim
([`boards/views/camim_auth.py`](boards/views/camim_auth.py)) ou local (Django LoginView).

## ⚠️ DEPLOY PENDENTE — feat: preservar `?next=` no login (2026-05-06)

Implementação da regra "Preservar URL após login" feita localmente em **2026-05-06**. **Não commitado, não deployado ainda.** Antes de mais nada: revisar diff, commitar, push e deployar.

### Arquivos modificados deste fix

- [`nossotrello/middleware.py`](nossotrello/middleware.py) — `LoginRequiredMiddleware` e `TermsMiddleware` passaram a usar `request.get_full_path()` (path + query) em vez de `request.path`, para preservar deep links como `/board/71/?card=1081`.
- [`boards/views/camim_auth.py`](boards/views/camim_auth.py) — `camim_login` grava em `request.session["camim_next"]`; `camim_callback` faz pop e redireciona, validando contra `//` e `/\` (anti open-redirect).
- [`CLAUDE.md`](CLAUDE.md) — este arquivo (novo).

### ⚠️ Arquivos untracked NÃO relacionados

- `.codex` — arquivo solto no working tree. Conferir o que é antes de commitar (possivelmente adicionar ao `.gitignore`).

### Como deployar

Ver [`deploy.sh`](deploy.sh) (prod) ou [`deploy-hml.sh`](deploy-hml.sh) (homol). Após `git pull` na VM, rodar migrations se necessário e reiniciar o gunicorn/uvicorn.

### Testar após deploy (aba anônima)

1. Pegar um link de card que abre direto: `https://tarefas.camim.com.br/board/<id>/?card=<id>` e abrir sem estar logado.
2. Deve cair em `/login/?next=%2Fboard%2F<id>%2F%3Fcard%3D<id>` (com a query preservada).
3. Clicar "Entrar com IDCamim" → após callback, abrir o board JÁ NO CARD certo (não na home).
4. Validar também o `TermsMiddleware`: usuário sem termos aceitos deve cair em `/legal/termos/?next=...` e voltar para a URL original após aceitar.

## Regra de design — Preservar URL após login (`?next=`)

Sempre que um usuário deslogado tentar acessar uma URL protegida, capturar o
caminho completo (path + query string) e propagar via `?next=<url>` por todo o
fluxo de autenticação, de modo que ao final ele caia na URL original — nunca em
uma home/dashboard genérico.

**Onde está implementado:**
- [`nossotrello/middleware.py`](nossotrello/middleware.py) — `LoginRequiredMiddleware` e
  `TermsMiddleware` usam `request.get_full_path()` (NÃO `request.path`) para preservar
  query strings em deep links como `/board/71/?card=1081`.
- [`boards/templates/registration/login.html`](boards/templates/registration/login.html) —
  botão IDCamim propaga `next` via query, form local via hidden input.
- [`boards/views/camim_auth.py`](boards/views/camim_auth.py) — `camim_login` grava em
  `request.session["camim_next"]`; `camim_callback` faz pop e redireciona, validando
  contra `//` e `/\` (anti open-redirect).

**Sanitização:** `next` SÓ pode começar com `/` e NÃO pode começar com `//` ou `/\`.
A `state` OAuth permanece sendo apenas anti-CSRF — não confundir com `next`.

## Outras notas

- O middleware de termos (`TermsMiddleware`) também redireciona para
  `/legal/termos/?next=...` — preserva o destino da mesma forma.
- Banco SQLite local em `db.sqlite3` durante dev; Postgres no docker-compose para prod/HML.

## Dívidas técnicas

### Mídia (vídeos/fotos) servida do `StoredFile` (bytea no Postgres RDS)

**Hoje:** todo upload de mídia entra como linha em `boards_stored_file` (campo `data bytea`) e o view `_stored_file_response` em [`boards/views/media_serve.py`](boards/views/media_serve.py) faz `SELECT data FROM stored_file WHERE id=...` carregando o blob inteiro pra memória do gunicorn a cada request — inclusive a cada Range request de vídeo.

**Problema:**

- Postgres não é storage de mídia. Cada Range hit no vídeo (`bytes=0-`, `bytes=2097152-`, …) faz nova query + nova alocação de memória de até 2MB (cap) → gargalo de CPU+memória+rede no Django ↔ RDS.
- Backup do RDS engorda com mídia binária — manter dados relacionais e blobs separados é prática padrão.
- Latência: a query RDS sai de us-east-1 mesmo quando o user é Brasil.

**Solução futura:** mover bytes pra S3 (mesma região da VM ou edge), guardar só metadados (`size`, `content_type`, `checksum`, `original_name`, S3 key) no `StoredFile`. `_stored_file_response` redireciona pra URL assinada do S3 ou faz proxy passando o Range adiante. Migração é gradual — checar `data IS NULL` significa "tá no S3".

**Bloqueio atual:** disco da VM não comporta migrar pra filesystem local como passo intermediário; ir direto pro S3 quando priorizado.

## Playbook — Cloudflare CDN na frente de `/media/serve/`

Não foi feito (depende de troca de DNS). Quando for feito, segue o roteiro:

1. Criar conta Cloudflare (free tier).
2. **Add a Site** → `camim.com.br`. Free plan.
3. Cloudflare lista os DNS records detectados — conferir se tudo apareceu (`tarefas.camim.com.br` deve estar lá como A → IP da VM).
4. Cloudflare entrega 2 nameservers tipo `xxx.ns.cloudflare.com`. Copiar.
5. No registrador onde o `camim.com.br` está (Registro.br ou onde for), trocar nameservers pelos da Cloudflare.
6. Esperar propagação (de minutos até 24h). Cloudflare avisa por e-mail quando validar.
7. Em **Rules → Cache Rules** criar regra:
   - Match: `URI Path` `starts with` `/media/serve/`
   - Action: `Eligible for cache`, `Edge TTL: 7 days`, `Browser TTL: 7 days`, `Cache Reserve: on`
8. (Opcional) Em **Speed → Optimization**: ativar Brotli; em **Network**: ativar HTTP/3, 0-RTT.
9. **Não cachear** endpoints autenticados — eles já mandam `Cache-Control` dinâmico, CF respeita; mas confirmar com `curl -I https://tarefas.camim.com.br/board/1/` que vem `cf-cache-status: DYNAMIC` ou `BYPASS`.

**Validar depois do switch:**

- `curl -I https://tarefas.camim.com.br/media/serve/<uuid>/` na primeira request → `cf-cache-status: MISS`
- Mesmo curl de novo → `cf-cache-status: HIT` (resposta vem do edge em ~30ms)
- Range request: `curl -H "Range: bytes=0-1023" -I ...` → deve voltar `206 Partial Content` (CF preserva Range).

**Limite free tier:** arquivos > 100MB não são cacheados (passam direto). Nossos vídeos hoje cabem.
