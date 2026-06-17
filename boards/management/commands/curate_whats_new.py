# boards/management/commands/curate_whats_new.py
"""
Rescreve os itens de Novidades com textos voltados ao usuário final.

- Busca cada item pelo commit_hash (curadoria manual).
- Itens técnicos (WebSocket, migrations, storage interno) são despublicados.
- Itens novos (sem entrada na curadoria) permanecem como foram importados
  e ficam visíveis no admin para você ajustar.

Uso:
    python manage.py curate_whats_new
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from boards.models import WhatsNewItem


# -------------------------------------------------------------
# Curadoria: commit_hash -> (emoji, título, descrição)
# Textos pensados no USUÁRIO: o que ele ganha, não o que foi feito.
# -------------------------------------------------------------
CURATED = {
    # --- 2026-06 ---
    "de6c16b": (
        "🏷️",
        "Escolha a cor da etiqueta na automação",
        "Na automação da coluna, quando a ação é \"Adicionar etiqueta\", agora tem "
        "um seletor de cor ao lado do nome. A etiqueta criada pela automação já "
        "nasce com a cor que você escolheu.",
    ),
    "9e7ee7b": (
        "✅",
        "Automação \"Marcar como Entregue\" agora entrega de verdade",
        "Quando uma automação da coluna marca o card como Entregue, agora ela faz "
        "tudo o que acontece quando você clica no botão \"Entregue\" do card: marca "
        "como entregue (com o ícone), desliga o aviso de prazo, registra no "
        "histórico e avisa os seguidores por e-mail e WhatsApp. Antes ela só mudava "
        "o status, sem avisar ninguém.",
    ),
    "f29b684": (
        "🎨",
        "Escolha a cor do seu bloco de código",
        "No canto do bloco de código (descrição e \"Nova Atividade\") apareceu um "
        "botãozinho colorido ao lado do \"Copiar\". Clique nele e escolha a cor do "
        "fundo e da fonte do código do seu jeito — fica salvo no seu usuário. Daí "
        "pra frente, todo bloco de código novo que você criar já nasce com essas "
        "cores. Os blocos que você já tinha feito continuam como estavam.",
    ),
    "bede5a8": (
        "💻",
        "Bloco de código com botão de copiar",
        "Nos editores do card (descrição e \"Nova Atividade\"), embrulhe um trecho "
        "entre três aspas (''' seu código ''' ou \"\"\" ... \"\"\") — ou três crases — "
        "e ele vira um bloco de código com fonte monoespaçada. No acompanhamento, o "
        "bloco aparece destacado e com um botão \"Copiar\" no canto. Útil pra colar "
        "um SQL, um curl ou um trecho de código sem virar texto solto. (As aspas "
        "triplas atendem o teclado ABNT, onde a crase é tecla morta.)",
    ),
    "fcf52ee": (
        "🖼️",
        "Editar quadro: nome e imagem na mesma janela",
        "Na home, o lápis (✏️) do quadro agora abre uma janelinha única onde você "
        "muda o nome e a imagem de capa de uma vez — pode trocar só o nome, só a "
        "imagem ou os dois. E o botão de trocar imagem fica sempre à mão, mesmo "
        "quando a capa atual deu algum problema.",
    ),
    "1200f63": (
        "✏️",
        "Edite uma automação já criada",
        "Agora é só clicar numa regra de automação da coluna para editá-la: o "
        "gatilho, a ação e os campos carregam no formulário e você salva por cima — "
        "sem precisar apagar e recriar a regra.",
    ),
    "1fb2a11": (
        "⚡",
        "Automação na coluna: card entra ou sai → faz algo",
        "No menu (⋮) de cada coluna agora tem \"Automação\". Você cria regras do "
        "tipo \"quando um card entra nesta lista\" ou \"quando um card sai\" e "
        "escolhe o que fazer: disparar um e-mail avisando alguém, mover o card "
        "para outra coluna, definir a data de entrega (+N dias), adicionar uma "
        "etiqueta ou marcar como entregue. Sem configuração complicada — escolhe "
        "o gatilho, a ação e pronto.",
    ),
    "e7790b4": (
        "📧",
        "Criar card a partir de e-mail",
        "No menu (☰) do quadro agora tem \"Criar Card From Email\": você configura "
        "uma caixa de e-mail (Gmail, KingHost...) e escolhe uma coluna. Todo e-mail "
        "novo que chegar vira um card nessa coluna — o assunto vira o título, o "
        "corpo vira a descrição e o remetente fica numa etiqueta. Dá pra definir de "
        "quanto em quanto tempo sincroniza. A senha é guardada criptografada e só "
        "serve pra ler a caixa. Sem nenhuma coluna no quadro, ele avisa que é "
        "preciso criar uma antes.",
    ),
    "77fc7ce": (
        "🎨",
        "Deixe a home com a sua cara",
        "Na home agora tem um botão de paleta (🎨) ao lado do menu. Abra e ajuste "
        "três coisas da página de uma vez: a cor do fundo dos painéis e do "
        "cabeçalho, o quanto ela fica transparente e o quanto fica fosca "
        "(desfoque). Mexa nos controles e a home muda na hora — a sua escolha "
        "fica salva neste navegador pra quando você voltar.",
    ),
    "3ce9d49": (
        "👥",
        "Mude quem vê o código compartilhado quando quiser",
        "Nos \"Códigos compartilhados\" do card agora dá pra ver exatamente quem "
        "tem acesso a cada segredo e mexer nisso a qualquer momento: em "
        "\"⚙️ Gerenciar acesso\" você marca um novo colega ou tira o acesso de "
        "alguém, sem precisar recriar nada — a chave continua criptografada e "
        "intacta. Só quem criou o segredo gerencia o acesso.",
    ),
    "c42a5dc": (
        "🔒",
        "Compartilhe um curl com a chave — sem deixar a chave à mostra",
        "No acompanhamento do card agora tem \"Códigos compartilhados\": cole um "
        "comando completo (um curl com a chave de API, por exemplo) e escolha "
        "exatamente quem pode abrir. O conteúdo é criptografado antes de salvar — "
        "ninguém além de você e dos colegas marcados consegue revelar, e cada "
        "abertura fica registrada. Quem não foi marcado vê só um cadeado. Assim o "
        "outro dev testa igualzinho ao que você fez, sem a chave virar texto solto.",
    ),
    "bbfa426": (
        "🔒",
        "Você decide o que do Tarefas vai pra rede social",
        "Nas configurações da sua conta tem agora a opção \"Compartilhar na rede social quadros do Tarefas\". Marcada (padrão), curtir um card ou compartilhar um quadro aparece no reel como sempre. Desmarcada, nada do Tarefas vai mais pro Espaço Social — e os \"curtiu um card\" e convites de quadro que você já tinha publicado somem do feed na hora.",
    ),

    "932dd67": (
        "🔢",
        "Cards contadores: números que se atualizam sozinhos",
        "No menu (⋮) da coluna agora tem \"Card contador\": ele cria um card fixo no "
        "topo da lista mostrando um número grande que se atualiza sozinho. Dá pra "
        "contar o total de cards, os entregues (no total ou nos últimos X dias), os "
        "não entregues, os com prazo vencido ou os parados há X+ dias. Ótimo pra ter "
        "o pulso da lista batendo o olho — e ele não atrapalha a contagem nem a "
        "auto-ordenação dos cards de verdade.",
    ),
    "8b8b92c": (
        "⚡",
        "Automação da coluna com mais ações",
        "A automação da coluna ganhou ações novas: além de disparar e-mail, mover "
        "o card e definir a data de entrega, agora dá pra copiar o card para outra "
        "lista, definir a data de início (+N dias) e marcar uma pessoa do quadro "
        "(cria o acompanhamento automaticamente). E as regras já criadas aparecem "
        "listadas, com o gatilho e a ação visíveis.",
    ),
    "419a677": (
        "🔗",
        "Automação fica visual, estilo fluxo",
        "Cada regra da coluna agora aparece como um fluxo: a caixa do gatilho, uma "
        "seta e a caixa da ação — fácil de bater o olho e entender o que acontece. "
        "Dá pra ter várias regras na mesma lista e o botão de adicionar mais ficou "
        "bem claro.",
    ),
    "8c08804": (
        "🔢",
        "Automação por quantidade de cards na lista",
        "Nova regra na automação da coluna: \"quando a lista ficar com MENOS de X "
        "cards\" ou \"com MAIS de X cards\", faça algo (avisar por e-mail, por "
        "exemplo). Perfeito pra colunas que agrupam tarefas — você é avisado quando "
        "a fila enche ou esvazia. Dispara só na virada, sem ficar repetindo.",
    ),
    "c74bf01": (
        "💬",
        "Automação que manda WhatsApp + a sua mensagem",
        "Agora a automação da coluna também pode enviar uma mensagem no WhatsApp, e "
        "você escreve o texto que quiser (vale pro e-mail também). Deixou em branco? "
        "Ele usa um texto padrão explicando o que aconteceu. O envio do WhatsApp "
        "depende da integração estar ligada — a regra já fica salva esperando.",
    ),
    "9bec57a": (
        "⏰",
        "Automação: card parado tempo demais",
        "Mais um gatilho na automação da coluna: \"quando um card ficar parado X "
        "dias nesta lista\". Aí ele pode ser movido pra outra coluna, gerar um "
        "aviso, ganhar uma etiqueta — o que você definir. A verificação roda uma "
        "vez por dia.",
    ),
    "d5c7f37": (
        "🏷️",
        "Etiquetas como no Trello",
        "As etiquetas do card ficaram do jeito que você já conhece do Trello: um "
        "catálogo de etiquetas coloridas que você marca pra aplicar e desmarca pra "
        "tirar, com um clique. Dá pra editar a cor e o nome de cada uma, e a mudança "
        "vale pra todo o quadro.",
    ),
    "24cdd9c": (
        "🖼️",
        "Papel de parede com cor sólida",
        "No menu do quadro, ao trocar o papel de parede, agora dá pra escolher uma "
        "cor sólida — vários tons prontos ou a cor exata que você quiser — em vez de "
        "uma imagem. Rápido, leve e do seu gosto.",
    ),
    "47d37e2": (
        "🎨",
        "Capa do card por cor",
        "Além de imagem, a capa do card agora pode ser uma cor sólida: clica na cor "
        "ao lado de escolher imagem e pronto. Ótimo pra dar um destaque rápido sem "
        "precisar subir foto nenhuma.",
    ),
    "285aefe": (
        "📋",
        "Importar do Trello colando o link de um card",
        "Na importação do Trello, se você colar o link de um card (…/c/…) em vez do "
        "link do quadro, agora ele tenta descobrir sozinho o quadro dono e importa "
        "tudo. Se o quadro for privado, aparece um aviso claro explicando que é só "
        "colar a URL do quadro inteiro.",
    ),

    # --- 2026-05 ---
    "643c38a": (
        "🛡️",
        "Espaço Social mais seguro",
        "Toda publicação agora passa por uma checagem em duas camadas: uma lista de termos proibidos que bloqueia na hora e uma IA que analisa o contexto. Se algo for marcado, você recebe um e-mail explicando o que aconteceu, qual cláusula dos Termos foi violada e a referência do caso. Em Menu → Minhas publicações sob moderação você acompanha tudo: o que está em análise, o que foi bloqueado e qualquer aviso recebido.",
    ),
    "9e5c754": (
        "🏢",
        "Régua de moderação ajustada pro ambiente corporativo",
        "A lista de termos bloqueados foi reforçada para refletir o que é esperado num ambiente profissional. Linguagem chula, ofensas, conteúdo sexual e discurso de ódio agora caem na cláusula 4.5 dos Termos de Uso (conduta no Espaço Social). Lembrete: o Espaço Social é uma rede profissional — registros podem ser usados em processos disciplinares.",
    ),
    "a3ca063": (
        "🦸",
        "Camilinho ilustrado em cada astral",
        "Toda vez que você marca como tá hoje no check-in do astral, o Camilinho aparece junto da publicação com uma carinha pra cada emoção — 13 humores no total, com 3 desenhos diferentes em cada (sorteado aleatoriamente). Animado pula, Apaixonado pulsa coração, Com raiva treme, Triste cai a cabecinha. Tudo animado por CSS, sem peso extra.",
    ),
    "2ef754d": (
        "💚",
        "Seu coração, sua cor",
        "Agora o coração das publicações é verde por padrão. E tem mais: segure o coração do feed por um instante e escolha entre 9 cores (vermelho, laranja, amarelo, verde, azul, roxo, preto, branco ou marrom). A cor que você escolher fica como SUA cor de coração em todos os corações que você toca.",
    ),
    "d9a1594": (
        "💌",
        "Notificações sociais com cara nova",
        "Comentários, menções, amizades e mensagens do chat agora chegam por e-mail num layout caprichado, com a marca da CAMIM social e um botão direto pra responder. A aba Espaço Social ganhou ícone próprio e abre com uma transição animada — nada de tela em branco enquanto carrega.",
    ),

    # --- 2026-04 ---
    "2c7d1bd": (
        "🧠",
        "Alerta de cards parecidos com IA",
        "Ao abrir um card, o NossoTrello verifica se já existe algo parecido em todos os quadros que você acessa — inclusive arquivados e na lixeira. Se achar, aparece um \"!\" ao lado do X; se não, um \"✓\" verde diz que o card é genuíno.",
    ),
    "53debaa": (
        "📤",
        "Compartilhe um post com a foto junto",
        "Agora, ao tocar em compartilhar, o texto e a imagem vão juntos pro WhatsApp, Instagram ou qualquer app. Nada mais de link seco.",
    ),
    "356be9a": (
        "🚀",
        "Compartilhar ficou muito mais fácil",
        "Um toque para mandar posts no WhatsApp, Instagram, Facebook ou salvar na sua página.",
    ),
    "4482063": (
        "🎓",
        "Primeiro acesso mais acolhedor",
        "Criou sua conta agora? Um tourzinho rápido te mostra por onde começar e quais são as funções principais.",
    ),
    "c25e142": (
        "✍️",
        "Veja seu colega digitando no card",
        "Quando duas pessoas abrem o mesmo card, agora dá pra ver em tempo real quem está escrevendo — letra por letra.",
    ),
    "bee7969": (
        "⚡",
        "Tudo em tempo real: chat, tracktime e acessos",
        "Chat, controle de horas e solicitações de acesso aparecem na hora, sem precisar recarregar a página.",
    ),
    "1a1a338": (
        "📰",
        "Compartilhe notícias com a equipe",
        "Achou uma notícia bacana? Compartilhe direto no feed com um toque.",
    ),
    "48a4c25": (
        "🤖",
        "Aba exclusiva pra Camila News",
        "Tudo que a Camila recomenda em notícias agora fica numa aba só dela. E funciona no app mobile também.",
    ),
    "60f9018": (
        "😊",
        "Check-in de humor mais rápido",
        "Os 4 humores mais comuns aparecem direto. Os outros ficam num \"Mais\" para não poluir a tela.",
    ),
    "f278fc1": (
        "💬",
        "Comentar posts ficou mais confortável",
        "Modal de comentários renovado, botão de enviar maior e o feed pausa o scroll sozinho quando você tá lendo.",
    ),
    "cc12808": (
        "🤝",
        "Seus amigos em destaque",
        "Na sua rede, agora aparecem duas fileiras de amigos com fotos maiores e nomes completos.",
    ),
    "d239624": (
        "💚",
        "Sua conversa com a Nutri.AI fica salva",
        "A AI lembra o que vocês já falaram e retoma de onde parou. Abra a qualquer momento.",
    ),
    "889077f": (
        "💚",
        "Nova aba: Saúde e Bem-Estar",
        "Converse com a Nutri.AI sobre alimentação, cansaço, hábitos — e receba orientações personalizadas.",
    ),
    "ae92eca": (
        "👀",
        "Descubra quem viu seu post",
        "Toque no contador de visualizações e veja exatamente quem alcançou sua publicação.",
    ),
    "4be760b": (
        "🖼️",
        "Feed em tela cheia",
        "A aba Novidades tem modo tela cheia para você aproveitar fotos e vídeos maiores.",
    ),
    "0e8a5c1": (
        "🧠",
        "Sugestões inteligentes para mover cards",
        "Baseado no jeito que você costuma trabalhar, o sistema sugere pra onde mover cada card.",
    ),
    "b855598": (
        "📱",
        "App mobile a caminho",
        "Em breve você terá um aplicativo no celular — a base já está pronta.",
    ),
    "68dfd11": (
        "🎉",
        "Telas de carregamento com seu time",
        "As frases que aparecem enquanto carrega agora citam pessoas e situações reais da equipe. Divirta-se!",
    ),
    "0c79b11": (
        "🔗",
        "Links de posts abrem bonitinho",
        "Clicou num link de post compartilhado? Ele abre em um modal, sem perder o que você tava fazendo.",
    ),
    "097871e": (
        "🔗",
        "Cada post tem seu próprio link",
        "Copie o link de qualquer post e compartilhe. Quem abrir vai direto pra ele.",
    ),
    "ba4b9a6": (
        "✨",
        "Posts com texto animado",
        "Crie posts só de texto com fundos coloridos e animações bonitas.",
    ),
    "0f71999": (
        "😍",
        "Reaja com qualquer emoji",
        "Mais de uma reação, melhor experiência de compartilhamento e prévia bonita quando o link é colado em qualquer lugar.",
    ),
    "cd2ae5e": (
        "❤️",
        "Curtir cards ficou melhor",
        "Capas, links clicáveis e visual ajustado no celular.",
    ),
    "23142db": (
        "✏️",
        "Edite posts — com histórico",
        "Pode corrigir aquele post depois de publicar. Tudo fica registrado para manter a transparência.",
    ),
    "9087de4": (
        "🎞️",
        "Reels numa aba própria",
        "Os vídeos em reel agora têm aba Novidades só pra eles. E o cartão de amizade nova ficou mais bonito.",
    ),
    "aea7141": (
        "😊",
        "Seu humor vira post automaticamente",
        "Ao fazer seu check-in de humor, ele aparece no feed para os amigos saberem como você tá.",
    ),
    "fe3d437": (
        "🎯",
        "Reações e encaminhamentos no chat",
        "Reaja em comentários, encaminhe mensagens pelo chat e copie pro WhatsApp em um toque.",
    ),
    "b80ed8e": (
        "🎨",
        "GIFs e stickers nos posts",
        "Agora dá pra postar GIFs e figurinhas no feed, não só no chat.",
    ),
    "3798f7e": (
        "💾",
        "Salve figurinhas direto do chat",
        "Viu uma figurinha que gostou? Salve pra usar depois com um toque.",
    ),
    "303669c": (
        "💬",
        "Chat com GIFs, stickers e confirmação de leitura",
        "Veja quando sua mensagem foi lida e use GIFs e figurinhas à vontade. Notificações ficaram mais espertas também.",
    ),
    "08fc3d6": (
        "🖼️",
        "Foto do perfil em tela cheia",
        "Toque na foto de qualquer perfil para vê-la em tela cheia.",
    ),
    "fbf6db9": (
        "📝",
        "Novos Termos de Uso",
        "Atualizamos os termos para cobrir a rede social interna, assistentes de AI e auditoria.",
    ),
    "87535ce": (
        "@",
        "Mencione colegas com @ em qualquer lugar",
        "Digite @ em comentários, cards e chat para citar quem você quiser — a pessoa recebe notificação.",
    ),
    "61c66ea": (
        "▶️",
        "Controle do auto-scroll no feed",
        "Toque na tela para pausar e retomar o scroll automático na hora que quiser.",
    ),
    "6272f83": (
        "🎞️",
        "Reels mais intuitivo",
        "Setas aparecem ao tocar, scroll suave e sugestões sincronizadas.",
    ),
    "38b394a": (
        "💬",
        "Chat liberado pra todo mundo",
        "Não precisa mais ser amigo pra conversar. E o reel organiza os últimos 3 dias por tipo de mídia.",
    ),
    "45c2677": (
        "🤝",
        "Pedidos de amizade mais claros",
        "Três botões (aceitar / recusar / ver perfil) pra decidir com tranquilidade. E os vídeos no reel tocam sozinhos.",
    ),
    "1a32db2": (
        "🎞️",
        "Auto-scroll inteligente no reel",
        "3 segundos para fotos e textos, espera o vídeo acabar, mostra os mais novos primeiro.",
    ),
    "cf0a7f8": (
        "🔍",
        "Foto do pedido de amizade maior",
        "Zoom 3x no avatar e botão de aceitar mais fácil de tocar. Sua preferência de feed fica salva.",
    ),
    "ac0b438": (
        "💬",
        "Contador de visualizações no post",
        "Veja quantas pessoas viram seu post. E o chat ficou mais estável e mais leve.",
    ),
}

# Commits que existem mas NÃO interessam ao usuário final.
# Vão ficar como is_published=False (somem do painel).
HIDE = {
    "999b6c6",  # Phase 0+1 WebSocket/RabbitMQ
    "7098e5c",  # DatabaseStorage PostgreSQL
    "ccd079e",  # Custom 502 maintenance page
    "87d777a",  # Rewrite carousel scroll-snap → transform
    "e3313a4",  # Auto-compress stickers client-side
    "057a558",  # Robust chat notification via cron
    "52cd00a",  # Chat button visible + migration fixes
    "9ca5cc4",  # Apply text_style in Novidades reel (detalhe interno)
    "46e3cd9",  # Post board invite activity to feed (detalhe interno)
    "c1c0942",  # iteração intermediária do "Editar Quadro" (final é fcf52ee)
}


class Command(BaseCommand):
    help = "Aplica curadoria humana nos itens de Novidades (textos voltados ao usuário)."

    def handle(self, *args, **opts):
        updated = 0
        hidden = 0

        for item in WhatsNewItem.objects.all():
            prefix = item.commit_hash[:7]

            if prefix in HIDE:
                if item.is_published:
                    item.is_published = False
                    item.save(update_fields=["is_published"])
                    hidden += 1
                continue

            if prefix in CURATED:
                emoji, title, description = CURATED[prefix]
                changed = False
                if item.emoji != emoji:
                    item.emoji = emoji
                    changed = True
                if item.title != title:
                    item.title = title
                    changed = True
                if item.description != description:
                    item.description = description
                    changed = True
                if not item.is_published:
                    item.is_published = True
                    changed = True
                if changed:
                    item.save(update_fields=["emoji", "title", "description", "is_published"])
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Curadoria aplicada. Atualizados: {updated}. Escondidos: {hidden}."
        ))
