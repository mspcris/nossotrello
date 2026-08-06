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

import subprocess

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from boards.models import WhatsNewItem


def _commit_datetime(commit_hash: str):
    """Data do commit via git; None se o hash não existir no clone."""
    try:
        out = subprocess.run(
            ["git", "show", "-s", "--format=%cI", commit_hash],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return parse_datetime(out.splitlines()[0]) if out else None
    except Exception:
        return None


# -------------------------------------------------------------
# Curadoria: commit_hash -> (emoji, título, descrição)
# Textos pensados no USUÁRIO: o que ele ganha, não o que foi feito.
# -------------------------------------------------------------
CURATED = {
    # --- 2026-08 ---
    "c1306e3": (
        "🧾",
        "Card que muda de quadro agora deixa rastro nos dois históricos",
        "Quando alguém movia um card para outro quadro, o Histórico do quadro "
        "de origem não registrava nada: o card sumia levando o próprio "
        "histórico junto, e não dava para saber quem tinha tirado, quando, "
        "nem para onde. Agora a mudança aparece nos dois lados, dizendo o "
        "nome dos quadros e das colunas — \"moveu este card do quadro Camim "
        "Gestão Web › TO DO para o quadro Tarefas Cristiano › A Fazer\". No "
        "histórico, o card que já foi embora mostra em que quadro ele está "
        "hoje, e clicar nele abre o card lá, no lugar certo.",
    ),
    "b867ffe": (
        "🔒",
        "Agora a comunidade pode ser aberta ou fechada — e só o dono decide",
        "Na página da comunidade apareceu o quadro \"Quem entra\", visível "
        "apenas para o dono, com um botão para abrir ou fechar o grupo. "
        "Fechada, quem está de fora não vê mais nada de dentro: feed, "
        "membros, chat e scrapbook ficam guardados e só aparece a capa com a "
        "ficha do grupo e o botão de pedir para participar. Aberta, qualquer "
        "pessoa do Espaço Social vê o conteúdo e entra sozinha, sem esperar "
        "aprovação — e quem já tinha pedido na fila entra na hora, sem ficar "
        "pendurado esperando alguém aprovar. Toda comunidade que já existia "
        "continua fechada, e no hub cada cartão agora mostra se é aberta ou "
        "fechada antes de você clicar.",
    ),
    "5be77f0": (
        "📲",
        "O Espaço Social agora vira um app no seu celular",
        "Abrindo o Espaço Social pelo celular, aparece um botão \"Instalar o "
        "app do Social\" no alto da página e um convite com o ícone grande. "
        "Um toque em \"Instalar agora\" e o Social ganha ícone na tela "
        "inicial do aparelho, abrindo em tela cheia, sem a barra do "
        "navegador — direto no seu feed. Quem preferir continuar no "
        "navegador toca em \"Agora não\" e o convite se recolhe por uma "
        "semana. No iPhone, o botão explica o caminho: Compartilhar e "
        "\"Adicionar à Tela de Início\".",
    ),
    "edf58f1": (
        "🌙",
        "A data e a descrição dos anexos voltaram a aparecer no card escuro",
        "Quem usa o card no tema escuro via os anexos numa faixa cinza onde a "
        "data e a hora do envio praticamente sumiam e a descrição exigia "
        "esforço para ler. Agora a linha do anexo escurece junto com o tema e "
        "os textos clareiam: dá para ver quem anexou, quando, e o que está "
        "escrito na descrição — sem forçar a vista.",
    ),
    "659ceeb": (
        "💬",
        "Agora dá para comentar nas publicações da comunidade",
        "Cada publicação do feed da comunidade ganhou um espaço de comentários "
        "logo abaixo — é escrever e enviar, sem sair da página. Quem publicou "
        "recebe um aviso por e-mail ou WhatsApp com um link que cai direto na "
        "publicação comentada. O scrapbook também cresceu: além de foto, agora "
        "guarda vídeo, com botões de Foto, Vídeo e Galeria que abrem a câmera "
        "ou o rolo do celular — no chat, os mesmos botões de Câmera e Galeria. "
        "E no celular as abas da comunidade ficaram lado a lado, com o número "
        "de membros clicável levando direto para a lista de pessoas.",
    ),
    "d7279e7": (
        "🏷",
        "Os chips e as legendas da vitrine da comunidade agora são editáveis",
        "A vitrine do tema dizia que era editável, mas os chips (tema, clima, "
        "objetivo e interesses) e as legendas das imagens vinham travados do "
        "momento em que a comunidade foi criada. Agora o dono (ou gestor) abre "
        "o \"Ajustar visual\" e encontra os quatro campos ali, junto do título "
        "e da frase de apoio: mudou o tema, mudam os chips, as legendas das "
        "três imagens e até a capa automática, tudo de uma vez. Errou na "
        "criação ou o grupo mudou de rumo? É só reescrever e salvar.",
    ),
    "4a24cb1": (
        "🖼",
        "As fotos do feed da comunidade agora aparecem inteiras",
        "Foto em pé no feed da comunidade aparecia cortada dentro de um "
        "retângulo deitado — cabeça e pés ficavam de fora. Agora cada foto "
        "aparece por completo, no formato em que foi tirada: se é em pé, ocupa "
        "um espaço em pé no meio do post; se é deitada, estica na largura. "
        "Vídeos seguem a mesma regra.",
    ),
    "e54a4b7": (
        "🎨",
        "Agora dá para escolher o papel de parede e as cores da sua comunidade",
        "No \"Ajustar visual\" da comunidade só dava para trocar a capa e as "
        "imagens da vitrine — o fundo da página e as cores vinham prontos e "
        "ninguém mexia. Agora o dono (ou gestor) escolhe o papel de parede numa "
        "galeria de doze fundos prontos, de Aurora e Meia-noite a Algodão-doce, "
        "Menta e Papel, e escolhe também a cor da comunidade numa cartela de "
        "doze paletas, que pinta os botões, as abas e os destaques da página. É "
        "só clicar no que quer e salvar. Quem não escolher nada continua com o "
        "visual automático de sempre, então nenhuma comunidade muda sozinha.",
    ),
    "bb33159": (
        "🌤",
        "O Track-time ao vivo ficou uma tela de ficar olhando o dia inteiro",
        "Quem acompanha o Ao vivo deixa a tela aberta o dia todo, e ela cansava "
        "a vista: branco puro, letras pretas e grossas, emoji em tudo quanto é "
        "canto e um monte de caixinha com borda. Agora o fundo é levemente "
        "frio, o texto é cinza-azulado, as bordas quase somem e só existe uma "
        "cor de destaque — o verde ficou reservado para o que está correndo "
        "agora. Os encerrados do dia viraram uma linha do tempo: horário à "
        "esquerda, o que foi feito no meio, tempo à direita, uma linha por "
        "track. As pessoas subiram para o topo, com uma bolinha verde em quem "
        "está com o cronômetro ligado, e o total da equipe aparece no "
        "cabeçalho. O cronômetro dos cards anda sozinho, sem os segundos "
        "piscando no canto do olho.",
    ),
    "84ff239": (
        "⏱",
        "A hora que você começou o track parou de sumir",
        "Quando um track-time era encerrado, a hora de início era apagada — só "
        "sobrava a de fim, e por isso os cards de \"Encerrados hoje\" apareciam "
        "com um tracinho no lugar do começo. O campo do início era o mesmo que o "
        "sistema usava para saber quem estava com o cronômetro ligado, e ao "
        "parar ele era limpo junto. Agora o início fica guardado. Nos tracks "
        "antigos, que já perderam esse dado, o painel calcula a hora de começo "
        "a partir do fim menos o tempo trabalhado e mostra com um \"~\" na "
        "frente, para você saber que ali é estimativa. Quem lança minutos na "
        "mão continua aparecendo como \"lançado às\", sem inventar horário.",
    ),
    "1bc4aba": (
        "🕒",
        "Track-time ao vivo: horários no card encerrado e visão por pessoa",
        "Na aba \"Ao vivo\", os tracks encerrados hoje só mostravam quanto tempo "
        "durou — para saber a que horas a pessoa começou e parou, você tinha que "
        "parar o mouse em cima e esperar a tarjinha aparecer. Agora o horário de "
        "início e de fim fica escrito no próprio card. E clicar em alguém (no "
        "total do dia, num card encerrado ou na foto de quem está com o timer "
        "rodando) deixa na tela só os tracks daquela pessoa, do mais cedo para o "
        "mais tarde, dando a linha do tempo do dia dela. Um botão \"Ver todos\" "
        "volta para a visão da equipe inteira.",
    ),
    "a828412": (
        "⏳",
        "Salvar suas configurações agora mostra que está salvando",
        "Ao mexer nas suas configurações e clicar em Salvar, nada indicava que "
        "o clique tinha funcionado — dava para achar que travou e clicar de "
        "novo. Agora a tela escurece e aparece a bolinha girando enquanto "
        "salva, do mesmo jeito que já acontecia nas ações do card. Vale para "
        "tudo que se salva ali: perfil, senha e foto.",
    ),
    "3388365": (
        "🧹",
        "Tocar na sua foto abre só as configurações",
        "No celular, tocar na sua foto abria as configurações e o seu perfil "
        "da rede social empilhados na mesma tela, com o botão Salvar preso no "
        "rodapé por cima de tudo. O Espaço Social morava dentro dessa tela "
        "quando nasceu; depois ganhou página própria e ninguém tirou daqui. "
        "Agora a tela mostra só as suas configurações, e o Espaço Social você "
        "acessa pela página dele. De quebra ela abre bem mais rápido: carrega "
        "dez vezes menos coisa.",
    ),
    "cab90a7": (
        "⋮",
        "O menu do card parou de recarregar a página no celular",
        "No celular, tocar nos três pontinhos de um card recarregava a página "
        "inteira e jogava o quadro de volta para o começo — o menu até abria, "
        "mas você não tinha tempo de usar. Havia um pedaço de código antigo "
        "que, quando o dedo tremia um pouquinho em cima do card, achava que "
        "você tinha arrastado o card e tentava avisar o servidor num endereço "
        "que não existe; ao dar erro, ele recarregava a página. No computador "
        "isso nunca aparecia, porque o mouse não treme. Já foi.",
    ),
    "56b9f98": (
        "🔄",
        "Puxar a tela para baixo atualiza o quadro",
        "No celular, arrastar o dedo para baixo não atualizava o quadro — para "
        "forçar, você tinha que sair da página e entrar de novo. Agora o gesto "
        "funciona: puxe para baixo com o quadro já no topo, aparece a setinha, "
        "e ao soltar a página recarrega. Puxar no meio de uma coluna comprida "
        "continua só rolando os cards, como deve ser, e arrastar de lado para "
        "passar de coluna não mudou nada.",
    ),
    "ed0f3eb": (
        "🧻",
        "O anexo parou de copiar a descrição do card",
        "Se você anexava um arquivo sem preencher a \"Descrição do anexo\", o "
        "anexo nascia com a descrição inteira do card colada dentro dele — por "
        "isso apareciam aqueles textos que você nunca escreveu ali, às vezes "
        "com página e meia de tamanho. O campo do card estava sendo enviado "
        "junto com o arquivo sem querer. Agora o anexo só recebe o que você "
        "digitar no campo dele; em branco significa em branco.",
    ),
    "8453d5c": (
        "📎",
        "A aba Anexos voltou a mostrar o anexo",
        "Quando você mandava um arquivo junto com um texto comprido, a aba "
        "Anexos despejava o texto inteiro embaixo do arquivo — o nome do "
        "arquivo virava um detalhe no meio de uma parede de letras, e as "
        "listas apareciam sem bolinha nem número. Agora o texto longo vem "
        "cortado em três linhas, com um \"ver mais\" para abrir e fechar, e "
        "listas, trechos de código e imagens coladas aparecem formatados. "
        "Também sumiu aquele espaço em branco que ficava sobrando quando o "
        "arquivo tinha sido enviado sem nenhum comentário.",
    ),
    "986528a": (
        "📐",
        "A largura das colunas agora vale no celular",
        "Você podia arrastar o ajuste de largura das colunas o quanto "
        "quisesse: no celular a coluna ficava sempre do mesmo tamanho. O "
        "layout do celular tinha uma largura fixa que passava por cima da sua "
        "escolha. Agora, se você escolher uma largura, ela vale no celular "
        "também — só não deixamos a coluna passar da borda da tela. Quem nunca "
        "mexeu no ajuste continua vendo a coluna ocupando quase a tela toda, "
        "como antes, e é isso que o valor padrão (240px) faz.",
    ),
    "680aee6": (
        "👤",
        "Clicar no nome de quem comentou abre o perfil",
        "Para ver o perfil de alguém que comentou você precisava tocar no "
        "comentário, esperar abrir o menuzinho e então escolher \"Perfil de "
        "fulano\". Agora é direto: clicou no nome, foi. Vale no feed, no reel e "
        "no painel lateral, inclusive para um comentário que acabou de ser "
        "escrito. Quem quiser reagir, responder ou denunciar continua tocando "
        "no resto da linha, como antes.",
    ),
    "74d4dd0": (
        "🧽",
        "Sumiu o texto solto que aparecia na tela",
        "Desde ontem aparecia uma anotação nossa de bastidor no meio da página, "
        "aquele texto começando com \"Player de vídeo em modal\". Era um "
        "comentário de código que escapou pra tela por um detalhe de sintaxe. "
        "Já foi.",
    ),
    "7cb0f7c": (
        "🧹",
        "O calendário não mostra mais o quadro por baixo",
        "Quando você abria o calendário, o quadro continuava ali embaixo: "
        "rolando um pouco apareciam o Controle de Colunas e o começo das "
        "colunas, como se fossem duas telas empilhadas. No celular isso ficava "
        "na cara, logo abaixo da grade do mês. Agora o calendário fica sozinho "
        "na tela, e o quadro volta quando você sai dele.",
    ),
    "28aa0b7": (
        "📱",
        "O calendário finalmente dá pra usar no celular",
        "No computador o calendário mostra a semana em sete colunas — e era "
        "isso que aparecia no celular também, espremido: cada dia ficava com "
        "dois dedos de largura e todo card virava \"Reuni…\". Agora, no "
        "celular, o calendário vira uma agenda: os dias vêm um embaixo do "
        "outro, o nome do card aparece inteiro e ainda diz de qual coluna ele "
        "é. A agenda já abre no dia de hoje, a data do dia fica grudada no topo "
        "enquanto você rola, e a tarja colorida de prazo continua ali dizendo o "
        "que está vencido, a vencer ou em dia. No mês, só aparecem os dias que "
        "têm card, então dá pra ver o mês inteiro numa rolada só. No computador "
        "nada muda.",
    ),
    "b4ecb42": (
        "🔢",
        "As abas do card dizem quanto tem dentro",
        "Para saber se um card tinha checklist ou anexo você precisava clicar na "
        "aba e conferir. Agora o número aparece do lado do nome — Checklists 3, "
        "Anexos 15 — e some quando não tem nada, para a barra não ficar poluída. "
        "A conta se atualiza na hora em que você adiciona ou remove, sem "
        "recarregar o card.",
    ),
    "8c9c182": (
        "🎬",
        "Vídeo no card agora abre e toca ali mesmo",
        "Clicar num vídeo anexado baixava o arquivo, e às vezes nem abria "
        "depois de baixado, porque o computador não tinha o codec. Agora ele "
        "toca numa janela por cima do card — e o Tarefas prepara sozinho uma "
        "versão que funciona em qualquer navegador, então o vídeo sempre abre. "
        "Além disso: arrastar um arquivo pra cima do campo Nova atividade "
        "prende ele ali com o ícone do tipo, você ainda escreve o que quiser e "
        "os dois vão juntos numa entrada só. E a linha do feed ficou curta — "
        "\"fulano anexou um vídeo\" — em vez de repetir o nome do arquivo e a "
        "descrição que já aparecem logo abaixo. Funciona também com o vídeo "
        "que o gravador de tela salva sem extensão no nome: antes ele entrava "
        "como arquivo qualquer, sem miniatura e sem player. Agora o Tarefas "
        "olha o conteúdo e reconhece o que o arquivo é de verdade — o mesmo "
        "passou a valer pra PDFs e imagens que chegavam sem extensão.",
    ),
    "da1c5d3": (
        "⏱️",
        "O botão Manual do Track-time avisa o que está faltando",
        "Você digitava os minutos, clicava em Manual e não acontecia nada — "
        "porque o lançamento também precisa do projeto e da atividade, e isso "
        "não estava dito em lugar nenhum. Agora o Tarefas fala: \"Selecione o "
        "projeto\" ou \"Selecione a atividade\", abre o balão de aviso em cima "
        "da caixa que falta e pisca ela por dois segundos, para você enxergar "
        "de primeira onde clicar. Quando dá certo, ele confirma o que foi "
        "lançado e guarda a escolha para o próximo lançamento. As caixas de "
        "seleção e os botões do Track-time também ficaram mais fáceis de "
        "enxergar, com contorno visível parado e iluminação ao passar o mouse.",
    ),
    # --- 2026-07 ---
    "d092d28": (
        "⏳",
        "Dá pra ver quando o Tarefas está trabalhando",
        "Mover o card pelo menu ⋮ leva alguns segundos e a tela ficava parada, "
        "sem dizer se o clique tinha pegado — aí você clicava de novo. Agora a "
        "tela escurece e aparece uma bolinha girando com o que está acontecendo "
        "(\"Movendo o card…\", \"Anexando contrato.pdf…\"), e o clique fica "
        "bloqueado até terminar. Vale pra mover, duplicar, arquivar, mandar pra "
        "Lixeira e anexar arquivo.",
    ),
    "301fa16": (
        "📥",
        "Arraste o arquivo direto pra cima do card",
        "Agora dá pra pegar um arquivo no computador e soltar em cima do card, "
        "no próprio quadro — sem abrir o card antes. Ele sobe como anexo daquele "
        "card e o card mostra \"Anexando…\" enquanto o envio acontece. Soltar "
        "vários de uma vez também funciona: eles sobem em fila. Se o arquivo "
        "passar de 50MB, o card avisa em vez de falhar calado. Antes, dependendo "
        "de onde você soltava, o navegador simplesmente baixava o arquivo de "
        "volta e nada era anexado.",
    ),
    "606908a": (
        "💤",
        "Quem parou de usar some das listas do Espaço Social",
        "Quem não entra no Tarefas há mais de 30 dias deixa de aparecer nas "
        "suas listas: amigos, sugestões, pedidos de amizade, lista do chat e "
        "os avisos de \"fulano e sicrano agora são amigos\". Assim a lista de "
        "amigos mostra quem realmente está por aqui. Nada é apagado: as "
        "publicações da pessoa continuam no ar, a amizade continua valendo e "
        "ela volta a aparecer sozinha no dia em que entrar de novo.",
    ),
    "79235ff": (
        "📎",
        "Anexo agora mostra o nome do arquivo",
        "Antes, ao anexar um arquivo no card, aparecia um código tipo "
        "\"79739e52-1334-4788…\" e um quadrado cinza vazio — dava pra achar que "
        "o anexo nem tinha subido. Agora aparece o NOME do arquivo, tanto na aba "
        "Anexos quanto na Atividade, com um ícone de folha mostrando a extensão "
        "(PDF, XLSX, DOCX, MP4…). A miniatura só aparece quando existe de "
        "verdade: a foto, a primeira página do PDF ou o primeiro quadro do "
        "vídeo. Vale igual pra quem arrasta o arquivo pro card e pra quem usa "
        "o botão de anexar.",
    ),
    "96f54bc": (
        "📸",
        "Sua foto do IDCamim aparece sozinha no Tarefas",
        "Nunca subiu uma foto de perfil aqui? Agora o Tarefas usa a foto do seu "
        "cadastro no IDCamim (Camim ID) no lugar do avatar genérico — ela aparece "
        "no topo, nos cards, no chat, no track-time e no Espaço Social. Se você "
        "subiu uma foto própria, ela continua valendo; só ficam as iniciais quando "
        "não há foto em nenhum dos dois.",
    ),
    "4d953e5": (
        "🚧",
        "Card em impedimento: marque quem está travando",
        "Todo card agora tem o botão \"Impedimento\" ao lado de \"Entregue\". Ao "
        "marcar, você escolhe (nas bolinhas grandes) quem está travando o card. O "
        "card ganha uma tarja vermelha na capa e as fotos dos responsáveis pulsando "
        "no board — dá pra ver de longe quem segura a tarefa. Cada responsável se "
        "libera clicando na própria foto; o dono do quadro pode liberar qualquer "
        "um. Quem é marcado recebe e-mail e WhatsApp avisando que o card depende "
        "dele. Quando o último se libera, a tarja some e a imagem da capa volta.",
    ),
    "ce04da4": (
        "⏳",
        "Dá pra ver que o clique aconteceu (impedimento e track-time)",
        "Ações que levavam alguns segundos pareciam não responder. Agora tem "
        "feedback na hora: marcar impedimento vira \"Marcando…\" com uma bolinha "
        "girando; ao liberar uma pendência a foto escurece com um spinner por cima; "
        "e o \"Atualizar\" do Ao Vivo mostra \"Atualizando…\".",
    ),
    "46a7a09": (
        "🖼️",
        "Escolheu uma cor por engano? A imagem da capa volta",
        "Antes, se você clicasse numa cor de capa, a imagem do card sumia pra "
        "sempre. Agora aparece um quadradinho com a miniatura da imagem anterior "
        "(com uma setinha ↺) na barra de cores — clicou, a imagem da capa volta.",
    ),
    "b428b1b": (
        "⏱️",
        "Track-time \"Ao vivo\" repaginado, com totais e encerrados do dia",
        "A tela do track-time ao vivo ganhou fotos maiores e fontes mais legíveis. "
        "Abaixo dela agora tem duas seções novas: \"Totais hoje\" (cada pessoa e "
        "quanto trabalhou no dia) e \"Encerrados hoje\" (os tracks que fecharam "
        "hoje, com o tempo total). Passe o mouse num card pra ver mais detalhes.",
    ),
    "0aa4fc3": (
        "⏲️",
        "Limite de tempo do track-time por pessoa (admin)",
        "No painel do track-time há uma aba \"Limites\" (só para administradores): "
        "dá pra ver e ajustar, por pessoa, quanto tempo o cronômetro roda antes de "
        "pedir confirmação e encerrar sozinho. Assim quem não esquece o track ganha "
        "mais folga, e quem esquece encerra mais cedo.",
    ),
    "b17d13a": (
        "📱",
        "No celular, mais espaço pros cards",
        "Na tela do celular a barra roxa de cima encolheu pra só a linha de ícones "
        "(a busca ficou na lupa do quadro) e a coluna de cards ficou larga, ocupando "
        "quase a tela toda — bem mais confortável de ler. Otimizado até para telas "
        "bem pequenas, como a de capa do Galaxy Z Flip.",
    ),
    "1b0ef9f": (
        "🔤",
        "Título do card sem negrito e mostrando por inteiro",
        "O título no card do modal saiu do negrito (que ficava pesado) e agora "
        "aparece inteiro, quebrando em quantas linhas precisar. No board ele corta "
        "com \"…\" pra não virar um paredão — e o texto completo aparece ao passar "
        "o mouse.",
    ),
    "1de4e2e": (
        "🌗",
        "Menções (@fulano) legíveis no modo escuro",
        "No modo escuro, a marcação de uma pessoa (@fulano) ficava com fundo claro "
        "e letra branca — quase invisível. Agora a menção tem contraste nos dois "
        "temas.",
    ),
    "4718464": (
        "🔠",
        "Fonte da \"Nova Atividade\" igual à da descrição",
        "O campo de escrever uma nova atividade no card usava uma letra menor que a "
        "da descrição. Agora ficaram do mesmo tamanho, mais confortável de escrever "
        "e ler.",
    ),
    "243b4d8": (
        "⚡",
        "Pedir acesso a um quadro ficou quase automático",
        "O formulário de pedido de acesso pedia nome, e-mail e telefone — que o "
        "IDCamim já tinha e o sistema já sabia. Agora esses dados aparecem "
        "prontos e você só informa posto, função e ramal, que o IDCamim não "
        "guarda. E se você já pediu acesso a algum quadro antes, o formulário "
        "some de vez: é só clicar no botão.",
    ),
    "22e88ca": (
        "🌓",
        "Sumiu a linha estranha na descrição do card no modo escuro",
        "No modo escuro, o campo de descrição (e o de Nova Atividade) mostrava "
        "uma moldura a mais por dentro, que não existia no modo claro. Agora o "
        "campo tem uma borda só, igual nos dois temas.",
    ),
    "cb26fd7": (
        "👑",
        "Ninguém mais te faz dono de um quadro sem avisar",
        "Antes, se alguém transferisse a titularidade de um quadro pra você, o "
        "quadro simplesmente mudava de mãos — você só descobria por acaso. Agora "
        "chega um convite no topo do quadro pra você aceitar ou recusar, e o "
        "quadro só é seu depois do aceite. Enquanto você não responder, ele "
        "continua com quem convidou. Recusou? Nada muda. Você também recebe "
        "e-mail e WhatsApp avisando, e quem convidou pode cancelar enquanto você "
        "não respondeu.",
    ),
    "b7fcaa4": (
        "🌓",
        "Escolheu o card escuro? Agora todos abrem escuro",
        "O tema claro/escuro do card virou uma escolha sua, não do card. Antes "
        "ele voltava pro claro sempre que a página recarregava, e parecia que "
        "cada card tinha o seu. Agora você escolhe uma vez e vale pra todos os "
        "cards, sempre — até se você entrar de outro computador.",
    ),
    "e63f8da": (
        "↩️",
        "Automação: devolver o card do DONE limpa a entrega",
        "Nova ação de automação: \"Marcar como NÃO entregue\". Use quando o card "
        "volta do DONE pra fila de tarefas — ela tira o \"Entregue\" e apaga a "
        "data de entrega, que não valia mais. O aviso de prazo por cores, que a "
        "entrega desliga, também volta a funcionar.",
    ),
    "a725892": (
        "👍",
        "O curtir do card voltou a funcionar em card pequeno",
        "Em card curto (só o título, sem capa nem etiqueta), o botão de curtir "
        "ficava escondido embaixo do menu ⋮ e não dava pra clicar. Ele mudou de "
        "lugar: agora fica no rodapé do card, ao lado do menu, sempre visível e "
        "clicável — em card de qualquer tamanho.",
    ),
    "79be0ae": (
        "🔤",
        "A descrição do card ficou maior e mais fácil de ler",
        "A letra da descrição era bem menor que a do título sem motivo. Agora ela "
        "tem o mesmo tamanho que o título tinha, e o título subiu um degrau — a "
        "hierarquia ficou clara e a leitura, bem mais confortável.",
    ),
    "87b88ff": (
        "🤝",
        "Compartilhe o quadro pelo @username",
        "No \"Compartilhar quadro\" agora dá pra convidar digitando o @username "
        "da pessoa (ex.: @leocarneiro) em vez do e-mail — igual aparece no perfil "
        "dela. Funciona com ou sem o @ na frente; se não achar ninguém com aquele "
        "username, o aviso diz isso claramente em vez de um erro genérico.",
    ),
    "b7931fb": (
        "⏳",
        "Colou uma imagem? Agora tem bolinha girando",
        "Ao colar (Ctrl+V) ou escolher uma imagem de capa no card, aparece na "
        "hora uma bolinha girando com \"Enviando imagem…\" enquanto ela sobe. "
        "Antes ficava uns segundos sem nenhum sinal e parecia que nada tinha "
        "acontecido — agora você sabe que está vindo coisa boa.",
    ),
    "c4b20b9": (
        "📌",
        "Escolha se o \"Controle de Colunas\" fica fixo ou rola junto",
        "O menu ⋮ da coluna \"Controle de Colunas\" voltou a abrir (ele abria "
        "escondido) e ganhou a opção \"📌 Travar coluna\": marcada, a coluna fica "
        "fixa à esquerda e as outras passam por trás (como era); desmarcada, ela "
        "rola junto com as demais — ótimo no celular, onde a coluna fixa tomava "
        "quase a tela toda. A escolha fica salva no aparelho: dá pra soltar no "
        "celular e manter travada no computador.",
    ),
    "ec61ac6": (
        "⏰",
        "\"Avisar em\" certo mesmo digitando a data à mão",
        "Ao digitar o Vencimento manualmente (sem usar o calendário), o campo "
        "\"Avisar em\" às vezes travava numa data maluca tipo 25/01/1902. "
        "Corrigido: agora ele acompanha o vencimento e sugere 5 dias antes, "
        "certinho — e se você escolher outra data de aviso, ela é respeitada.",
    ),
    "2655ea0": (
        "👁️",
        "Card mais organizado: olho à esquerda, contador à direita",
        "No card, o olho de seguir agora mora sempre no canto esquerdo, e o "
        "contador vermelho de novidades aparece no direito — cada um no seu "
        "lugar, sem trocarem de posição. E no modo \"Arquivar Cards\" o botão "
        "de arquivar voltou pro canto superior direito do card: é nele que você "
        "clica pra arquivar cada card (com confirmação).",
    ),
    "f8d12f2": (
        "📝",
        "Criou o card? Ele já abre pra você continuar",
        "Ao criar um card pelo \"+ Card\" — digitou o título e deu Enter (ou "
        "clicou em Adicionar Card) — o card novo já abre na hora, pronto pra "
        "você preencher descrição, prazo, etiquetas e o que mais precisar. "
        "Menos cliques entre criar e escrever.",
    ),
    "d7af5ad": (
        "👓",
        "Textos legíveis em qualquer papel de parede",
        "O seu @usuário no topo e o caminho \"Todos os Quadros → nome do "
        "quadro\" ganharam um contorno escuro suave. Agora dá pra ler numa boa "
        "mesmo quando o papel de parede do quadro é claro ou branco.",
    ),
    "f0a6fe2": (
        "🔗",
        "Track-time com endereço próprio",
        "O Track-time agora tem página própria: tarefas.camim.com.br/track-time/painel/. "
        "O item do menu lateral leva direto pra lá, e a aba que você está vendo "
        "fica na URL — aperte F5 à vontade que você continua no Track-time, na "
        "mesma aba. Dá até pra favoritar a aba \"Hoje\" no navegador.",
    ),
    "4b725ee": (
        "📅",
        "Track-time: aba \"Hoje\" + filtros e relatório",
        "No Track-time agora tem a aba \"Hoje\": veja o que a galera fez no dia, "
        "com gráfico por hora e navegação para dias anteriores. E nas abas Hoje, "
        "Semana e Mês você pode filtrar por usuário ou por projeto, exportar o "
        "resultado em CSV (abre direto no Excel) ou gerar uma versão para "
        "imprimir — perfeito para fechar o relatório de alguém ou de um projeto.",
    ),
    # --- 2026-06 ---
    "409b83b": (
        "📌",
        "A coluna \"Controle de Colunas\" agora fica fixa",
        "A coluna de totais (\"Controle de Colunas\") agora gruda na esquerda e "
        "fica sempre visível enquanto você rola as outras colunas para o lado. "
        "Assim você nunca perde de vista os contadores nem precisa voltar a "
        "rolagem toda para clicar numa coluna.",
    ),
    "e8352da": (
        "🎯",
        "Clique no contador e a board pula para a coluna",
        "Na coluna \"Controle de Colunas\", clique em qualquer pílula (ex.: "
        "\"02 Bloqueado\") e a board rola na hora até aquela coluna e a destaca "
        "com um flash. Ótimo para boards largas com muitas colunas.",
    ),
    "04cc0a3": (
        "📋",
        "Cole uma imagem e já vira um card com capa",
        "No \"+ Card\", agora você pode colar (Ctrl+V) uma imagem direto: ela vira "
        "a capa do card, o card é criado na hora e já abre pra você preencher o "
        "nome e a descrição. Se você não digitar um nome, ele entra como \"Card "
        "criado por <você>\".",
    ),
    "b6d4c94": (
        "🔒",
        "Só o dono compartilha o quadro",
        "Agora apenas o dono do quadro pode adicionar pessoas a ele — tanto pelo "
        "botão \"Compartilhar quadro\" quanto pelo painel social. Quem é editor ou "
        "visualizador não compartilha mais o quadro de outra pessoa. Isso evita "
        "convites indevidos e conflitos de acesso.",
    ),
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
    # partes intermediárias de features de 17/07 já cobertas por 1 entrada só
    "cd02aef",  # impedimento parte 1 -> coberto por 4d953e5
    "6a5ce5c",  # seletor de impedimento (redesenho) -> 4d953e5
    "a76acd7",  # impedimento 2a (responsáveis acima do feed) -> 4d953e5
    "d86ef61",  # impedimento 2b (tarja na capa) -> 4d953e5
    "2776ff1",  # track-time "Totais hoje" -> coberto por b428b1b
    "47ab478",  # mobile coluna larga -> coberto por b17d13a
    "6a821bc",  # mobile header compacto (parte) -> b17d13a
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
    "b5bb636",  # miniatura de vídeo — já descrita na entrada 79235ff
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

        # Hashes curados que o sync não importou (ele só traz commits `feat:`):
        # cria o item aqui — é assim que fixes visíveis entram nas Novidades.
        created = 0
        existing = {
            h[:7] for h in WhatsNewItem.objects.values_list("commit_hash", flat=True)
        }
        for prefix, (emoji, title, description) in CURATED.items():
            if prefix in existing:
                continue
            WhatsNewItem.objects.create(
                commit_hash=prefix,
                emoji=emoji,
                title=title,
                description=description,
                published_at=_commit_datetime(prefix) or timezone.now(),
                is_published=True,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Curadoria aplicada. Atualizados: {updated}. Criados: {created}. Escondidos: {hidden}."
        ))
