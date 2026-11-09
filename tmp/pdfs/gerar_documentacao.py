from pathlib import Path
import json
import math
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/pdf/NeuroTriagem_AI_Documentacao_Tecnica.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)
for name, file in [
    ("Sans", "segoeui.ttf"), ("Bold", "segoeuib.ttf"), ("Book", "georgia.ttf"),
    ("Italic", "segoeuii.ttf"), ("Mono", "consola.ttf"),
]:
    pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / file)))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Bold", italic="Italic", boldItalic="Bold")
W, H = A4
L = 45
R = W - L
CW = R - L
INK = "#173435"
DARK = "#102F32"
TEAL = "#006F68"
MUTE = "#446263"
LINE = "#BCCBC5"
PALE = "#EDF4EF"
WHITE = "#FFFFFF"
BG = "#FCFBF7"
GOLD = "#B55D32"
WARM = "#FAF0E5"
C = Canvas(str(OUT), pagesize=A4, pageCompression=1, lang="pt-BR")
C.setTitle("NeuroTriagem.AI | Documentação técnica do protótipo")
C.setSubject("Arquitetura, hardware, firmware, software, modelos e operação")
C.setAuthor("Documentação do projeto NeuroTriagem.AI")
titles = [
    "NeuroTriagem.AI", "Guia de leitura", "Arquitetura do sistema", "Hardware e pinagem",
    "Oximetria e pulso", "Face e braços na webcam", "Trajetórias do joystick",
    "Protocolo serial USB", "Classificação experimental", "O que a floresta aprendeu",
    "Instalação e gravação", "Roteiro de uma avaliação", "Como ler a tela final",
    "Diagnóstico de falhas", "Verificação e limites", "Fontes e rastreabilidade",
]


def color(s):
    return colors.HexColor(s)


def rect(x, y, w, h, fill=None, edge=None, lw=0.7):
    C.setLineWidth(lw)
    if fill:
        C.setFillColor(color(fill))
    if edge:
        C.setStrokeColor(color(edge))
    C.rect(x, H-y-h, w, h, stroke=bool(edge), fill=bool(fill))


def line(x1, y1, x2, y2, shade=LINE, lw=.7):
    C.setStrokeColor(color(shade))
    C.setLineWidth(lw)
    C.line(x1, H-y1, x2, H-y2)


def circ(x, y, r, shade):
    C.setFillColor(color(shade))
    C.circle(x, H-y, r, stroke=0, fill=1)


def label(x, top, val, size=10, font="Sans", shade=INK, align="left"):
    C.setFillColor(color(shade))
    C.setFont(font, size)
    meth = {"left": C.drawString, "right": C.drawRightString, "center": C.drawCentredString}[align]
    meth(x, H-top-size, val)


def block(content, x, y, width, size=11, leading=None, font="Sans", shade=INK, draw=True):
    style = ParagraphStyle("body", fontName=font, fontSize=size, leading=leading or size*1.49,
                           textColor=color(shade), alignment=TA_LEFT, splitLongWords=True)
    p = Paragraph(content, style)
    _, h = p.wrap(width, 10000)
    if draw:
        p.drawOn(C, x, H-y-h)
    return h


def navlink(n, x, y, w, h):
    C.linkRect("", f"p{n}", (x, H-y-h, x+w, H-y), relative=0, thickness=0)


def bookmark(n):
    C.bookmarkPage(f"p{n}")
    C.addOutlineEntry(titles[n-1], f"p{n}", level=0)


def footer(n, refs):
    line(L, 788, R, 788)
    label(L, 797, "Fontes   " + refs, 8.1, "Sans", MUTE)
    navlink(16, L, 791, 310, 23)
    label(R-30, 797, "Sumário", 8.1, "Sans", TEAL, "right")
    navlink(2, R-87, 791, 61, 22)
    label(R, 795, f"{n:02d}", 10, "Bold", INK, "right")


def start(n, section, lead, refs):
    global y
    bookmark(n)
    rect(0, 0, W, H, BG)
    label(L, 30, "NEUROTRIAGEM.AI", 9, "Bold", TEAL)
    label(R, 30, section.upper(), 8.4, "Bold", MUTE, "right")
    line(L, 50, R, 50)
    label(L, 69, titles[n-1], 29, "Book")
    y = 119 + block(lead, L, 119, CW, 12.1, 17.5, shade=MUTE) + 20
    footer(n, refs)


def end():
    print(f"{C.getPageNumber():02d}  fim do conteúdo {y:.0f}")
    if y > 784:
        raise ValueError(f"Conteúdo excede a página {C.getPageNumber()}: {y:.0f}")
    C.showPage()


def h2(t):
    global y
    label(L, y, t, 14.3, "Bold")
    y += 27


def body(s, size=10.8, after=12):
    global y
    y += block(s, L, y, CW, size) + after


def note(title, s, warm=False):
    global y
    col, bg = (GOLD, WARM) if warm else (TEAL, PALE)
    h = block(s, 0, 0, CW-30, 10.2, 15, draw=False)
    rect(L, y, CW, 39+h, bg)
    rect(L,y,3,39+h,col)
    label(L+14, y+8, title, 11.3, "Bold", col)
    block(s,L+14,y+26,CW-30,10.2,15)
    y += 51+h


def table(heads, rows, widths, size=10.2, pad=8):
    global y
    xs=[L]
    for w in widths:
        xs.append(xs[-1]+w)
    assert abs(xs[-1]-R) < 1
    rect(L,y,CW,25,DARK)
    for i,t in enumerate(heads):
        label(xs[i]+8,y+6,t,9,"Bold",WHITE)
    y+=25
    for j,row in enumerate(rows):
        specs=[(s, xs[i]+8, widths[i]-16, "Bold" if i==0 else "Sans") for i,s in enumerate(row)]
        hs=[block(s,x,0,w,size,size*1.4,f,draw=False) for s,x,w,f in specs]
        rh=max(hs)+pad*2
        rect(L,y,CW,rh, "#F1F5F0" if j%2==0 else BG)
        for s,x,w,f in specs:
            block(s,x,y+pad,w,size,size*1.4,f)
        line(L,y+rh,R,y+rh)
        y+=rh
    y+=16


def code(lines, size=9.2):
    global y
    rect(L,y,CW,len(lines)*15+20,DARK)
    for i,t in enumerate(lines):
        assert pdfmetrics.stringWidth(t,"Mono",size)<CW-18, t
        label(L+11,y+8+15*i,t,size,"Mono","#F3F8F3")
    y+=len(lines)*15+33


def step(num, title, detail):
    global y
    label(L,y-1,f"{num:02d}",15,"Book",TEAL)
    label(L+38,y,title,12.3,"Bold")
    h=block(detail,L+38,y+20,CW-38,10.5,15)
    y+=h+34
    line(L,y-6,R,y-6)
    y+=4


def arrow(x1,y1,x2,y2,shade=TEAL,lw=1.3):
    line(x1,y1,x2,y2,shade,lw)
    a=math.atan2(y2-y1,x2-x1)
    for d in (-.55,.55):
        line(x2,y2,x2-5*math.cos(a+d),y2-5*math.sin(a+d),shade,lw)


def shape_points(idx):
    if idx == 2:
        return [(math.sin(i*math.tau/48),-math.cos(i*math.tau/48)) for i in range(48)]
    v=([(-1,-1),(1,-1),(1,1),(-1,1)] if idx==0 else [(0,-1),(.866,.5),(-.866,.5)])
    count=48//len(v)
    pts=[]
    for i in range(48):
        k=i//count
        t=(i%count)/count
        a,b=v[k],v[(k+1)%len(v)]
        pts.append((a[0]*(1-t)+b[0]*t,a[1]*(1-t)+b[1]*t))
    return pts


# Capa
bookmark(1)
rect(0,0,W,H,DARK)
label(L,44,"DOCUMENTAÇÃO TÉCNICA",10,"Bold","#9ED7C0")
label(R,44,"09 NOV 2026",9.6,"Sans","#C3D7CE","right")
line(L,72,R,72,"#64827C")
label(L,113,"NeuroTriagem.AI",44,"Book",WHITE)
block("Da aquisição de sinais à<br/>classificação experimental",L,200,CW,25,34,"Sans","#CBE7D5")
block("Como a BitDogLab, a webcam e o aplicativo desktop compõem uma avaliação de sinais vitais, assimetria facial e movimento dos braços.",L,312,CW-47,14.2,21.5,"Sans","#EBF3ED")
line(L,423,R,423,"#64827C")
label(L,441,"PERCURSOS DE REFERÊNCIA DO JOYSTICK",8.7,"Bold","#9ED7C0")
for i,(nm,xx) in enumerate(zip(["Quadrado","Triângulo","Círculo"],[L+79,W/2,R-79])):
    cy=538
    for off in [-40,-20,0,20,40]:
        line(xx-48,cy+off,xx+48,cy+off,"#294B4B",.4)
        line(xx+off,cy-48,xx+off,cy+48,"#294B4B",.4)
    pts=[(xx+x*38,cy+y0*38) for x,y0 in shape_points(i)]
    for k,pt in enumerate(pts):
        endpt=pts[(k+1)%48]
        line(*pt,*endpt,"#85C7AC",.9)
        circ(*pt,1.4,"#ACDEC3")
    circ(*pts[0],4.1,"#EFB984")
    label(xx,605,nm,11,"Sans",WHITE,"center")
line(L,664,R,664,"#64827C")
block("Protótipo para demonstração e pesquisa. A classificação descreve regras programadas e aprendidas com cenários sintéticos. A capacidade de confirmar ou excluir AVC ainda não foi avaliada clinicamente.",L,688,CW-29,11.5,17,"Sans","#CCE0D4")
label(L,793,"HARDWARE   /   FIRMWARE   /   SOFTWARE   /   MODELOS",8.4,"Bold","#9ED7C0")
C.showPage()

# Sumário
start(2,"Orientação","O protótipo reúne quatro coletas em uma sessão local. A documentação acompanha os dados desde os sensores até o resultado exibido ao operador.","A1, A2, M1, F1")
h2("Sumário")
def toc(colx, start_y, items):
    for i,(page,name) in enumerate(items):
        ty=start_y+i*29
        line(colx,ty+23,colx+240,ty+23)
        label(colx,ty,f"{page:02d}",10.5,"Bold",TEAL)
        label(colx+24,ty,name,10.1,"Sans")
        navlink(page,colx,ty-1,240,26)
toc(L,y,[(i,titles[i-1]) for i in range(3,10)])
toc(L+265,y,[(i,titles[i-1]) for i in range(10,17)])
y+=221
h2("Alcance da versão documentada")
body("O operador conduz a sessão pelo computador e pelos dois botões da placa. O firmware estima pulso e saturação e descreve três trajetórias. No computador, dois modelos de visão extraem medidas de face e braço. Ao final, uma floresta treinada com regras produz uma classe experimental.")
body("O desenho conceitual do projeto inclui Wi-Fi, ECG, fala e um alerta para priorização na fila do SUS. O fluxo executável usa serial USB e dois testes por vídeo. ECG, avaliação da fala e encaminhamento automático à equipe médica permanecem fora desta versão.")
note("Como interpretar esta edição","Pinagem e temporizações vêm do código C. A interface e os atributos vêm do aplicativo Python. As métricas são identificadas pela origem: testes de software, validação interna de visão ou experimento sintético.")
end()

# Arquitetura
start(3,"Arquitetura","A placa mede e resume os sinais físicos. O computador recebe eventos, processa imagens e reúne os resultados da sessão.","A1, A2, V1, J1, M1, F1")
def box(x,yy,w,hh,title,detail,bg=PALE):
    rect(x,yy,w,hh,bg,LINE)
    label(x+10,yy+7,title,11,"Bold",TEAL)
    block(detail,x+10,yy+26,w-20,9.4,13)
top=y
box(L,top,166,64,"BitDogLab","Oxímetro óptico e joystick de dois eixos.")
box(L,top+91,166,64,"Webcam","Quadros de vídeo para face e braços.")
box(L+210,top,294,64,"Leitores de porta serial","O leitor de vitais interpreta OXI. O leitor do joystick organiza eventos e métricas por figura.")
box(L+210,top+91,294,64,"Motores de visão","Um detector facial e um estimador de pose transformam imagens em graus, razão e lado.")
arrow(L+170,top+32,L+205,top+32)
arrow(L+170,top+123,L+205,top+123)
y+=177
table(["Dados","Destino no computador","Efeito na sessão"],[
    ["BPM e SpO₂","Leitor da pré-triagem","Dois atributos da floresta e dois cartões no resultado."],
    ["Face e braço","Sessão facial e motor de pose","Três atributos da floresta e dois cartões no resultado."],
    ["Joystick","Sessão de trajetórias","Tabela descritiva por figura. O evento final libera a classificação."],
],[113,165,CW-278])
h2("Quem controla cada recurso")
body("Em <b>main.py</b>, MainWindow organiza seis telas em um QStackedWidget. A transição libera a porta da pré-triagem antes da câmera, troca o uso da webcam entre face e braços e volta a abrir a porta para o joystick. A leitura serial roda em threads e atualiza a interface por sinais Qt.")
body("Ao finalizar, o aplicativo reúne atributos, previsão, estado do modelo, data/hora e sessão do joystick. A tela final consulta essa avaliação em memória. O fluxo entregue não oferece histórico em banco, gravação de vídeo ou envio automático de resultados.")
end()

# Hardware
start(4,"Sistema embarcado","O alvo de compilação é o Raspberry Pi Pico com RP2040 na BitDogLab. Os números abaixo são GPIOs do microcontrolador.","F1, F2, F3")
table(["Componente","Ligação no firmware","Função"],[
    ["Oxímetro óptico","I²C0 · SDA GP0, SCL GP1<br/>0x57 · 400 kHz","Módulo GY-MAX3010X. O driver lê os canais vermelho e infravermelho."],
    ["Joystick","VRX GP27 / ADC1<br/>VRY GP26 / ADC0","Dois eixos analógicos. O centro é medido a cada sessão."],
    ["Botões A e B","GP5 e GP6, com pull-up","A inicia trajetórias. B inicia o oxímetro. A troca de modo interrompe a atividade em curso."],
    ["Display OLED","I²C1 · SDA GP14, SCL GP15<br/>0x3C · 400 kHz","O driver SSD1306 usa uma área de 128 × 32 pixels para instruções e resultados."],
    ["Matriz de LEDs","GP7 · saída PIO","Matriz 5 × 5. Verde marca a posição e azul marca o alvo do joystick."],
    ["Buzzer","GP21 · saída PWM","Sinal sonoro quando o oxímetro obtém seu primeiro resultado estável."],
    ["USB e webcam","USB CDC até o PC<br/>Webcam acessível pelo OpenCV","O cabo USB de dados transporta a serial. O computador captura as imagens diretamente."],
],[115,164,CW-279],9.9,7)
h2("Conferência antes de ligar")
body("Identifique SDA e SCL do módulo óptico pelo conector I²C0. A UART de console está desativada para liberar GP0 e GP1. A pinagem de sinal está definida nos fontes. A tensão de alimentação e a ordem física dos terminais devem ser conferidas na identificação do módulo utilizado.")
note("Controles locais","A placa pode executar a aquisição sem o computador. Para acompanhar uma sessão no aplicativo, conecte o leitor serial antes de acionar o botão correspondente. O firmware aplica debounce de 200 ms aos botões.")
end()
