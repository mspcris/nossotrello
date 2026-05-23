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
    # --- 2026-05 ---
    "643c38a": (
        "🛡️",
        "Espaço Social mais seguro",
        "Toda publicação agora passa por uma checagem em duas camadas: uma lista de termos proibidos que bloqueia na hora e uma IA que analisa o contexto. Se algo for marcado, você recebe um e-mail explicando o que aconteceu, qual cláusula dos Termos foi violada e a referência do caso. Em Menu → Minhas publicações sob moderação você acompanha tudo: o que está em análise, o que foi bloqueado e qualquer aviso recebido.",
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
