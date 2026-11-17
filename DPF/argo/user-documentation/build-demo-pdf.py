#!/usr/bin/env python3
"""Build the copyable two-page demo handout. Requires reportlab."""
from pathlib import Path
from html import escape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parent
PDF = ROOT / 'DPF-HBN-two-tenant-demo.pdf'
FONT_DIR = Path('/usr/share/fonts/truetype/dejavu')
for name, file in [('Body','DejaVuSans.ttf'),('Bold','DejaVuSans-Bold.ttf'),('Code','DejaVuSansMono.ttf')]:
    pdfmetrics.registerFont(TTFont(name,str(FONT_DIR/file)))
W,H=landscape(A4)
M=36
INK=colors.HexColor('#172638');MUTED=colors.HexColor('#536579')
GREEN=colors.HexColor('#76b900');BLUE=colors.HexColor('#2475aa')
LIGHT=colors.HexColor('#f1f5f8');BORDER=colors.HexColor('#dce4ec')
URL='https://github.com/kirson-git/dsx-os/blob/main/DPF/README.md'
PROXY='ProxyCommand=kubectl -n dpf-operator-system exec -i dpf-hbn-recovery-access -- nc %h %p'
EUROPE=f"ssh -o \\\n  '{PROXY}' \\\n  ubuntu@192.168.0.231"
ASIA=f"ssh -o \\\n  '{PROXY}' \\\n  root@192.168.0.232"
READY='kubectl -n dpf-operator-system get dpus\nkubectl -n dpf-operator-system get pod dpf-hbn-recovery-access'
ADDRESS="DATA_IF=$(ip -4 route show default | awk '/default/ {print $5; exit}')\nip -4 addr show dev \"$DATA_IF\"; ip -4 route show default"
INTERNET="ping -4 -I $DATA_IF -c 3 -W 2 cisco.com\ncurl --noproxy '*' --interface $DATA_IF --connect-timeout 5 --max-time 15 \\\n  -sS -o /dev/null -w 'HTTP=%{http_code} source=%{local_ip}\\n' https://www.cisco.com"
PEER_EU='ping -4 -I $DATA_IF -c 3 -W 2 10.0.0.1'
PEER_AS='ping -4 -I $DATA_IF -c 3 -W 2 10.0.0.2'
c=canvas.Canvas(str(PDF),pagesize=(W,H))
c.setTitle('DPF + HBN | Europe and Asia demo')
c.setAuthor('NICo / DPF Lab')


def text(x,y,value,size=11,font='Body',color=INK):
    c.setFillColor(color);c.setFont(font,size);c.drawString(x,y,value)


def paragraph(x,top,width,value,size=10.5,color=MUTED):
    p=Paragraph(value,ParagraphStyle('p',fontName='Body',fontSize=size,leading=size*1.4,textColor=color))
    _,h=p.wrap(width,H);p.drawOn(c,x,top-h);return h


def box(x,top,width,height,fill=LIGHT):
    c.setFillColor(fill);c.setStrokeColor(BORDER);c.roundRect(x,top-height,width,height,7,fill=1,stroke=1)


def code(x,top,width,value,size=9.2):
    lines=value.splitlines();leading=size*1.45;height=18+len(lines)*leading
    box(x,top,width,height)
    for n,line in enumerate(lines):
        assert pdfmetrics.stringWidth(line,'Code',size)<=width-24, line
        text(x+12,top-14-n*leading,line,size,'Code')
    return height


def header(kicker,title,subtitle,page):
    c.setFillColor(GREEN);c.rect(0,H-7,W,7,fill=1,stroke=0)
    text(M,H-32,kicker,9,'Bold',BLUE)
    text(M,H-62,title,25,'Bold')
    text(M,H-83,subtitle,10.5,color=MUTED)
    c.setStrokeColor(BORDER);c.line(M,36,W-M,36)
    text(M,22,'DPF / HBN lab  |  Expected demo outcomes; verify readiness before presenting.',8,color=MUTED)
    text(W-91,22,f'{page} / 2',8,'Bold',MUTED)
    c.linkURL(URL,(M,16,M+170,32),relative=0)


def arrow(x1,y1,x2,y2,color=BLUE):
    c.setStrokeColor(color);c.setFillColor(color);c.setLineWidth(1.6)
    c.line(x1,y1,x2,y2)
    p=c.beginPath();p.moveTo(x2,y2);p.lineTo(x2-7,y2+3.5);p.lineTo(x2-7,y2-3.5);p.close()
    c.drawPath(p,fill=1,stroke=0)


header('DEMO GUIDE / 01','Connect to Europe and Asia','Two Ubuntu servers. Separate HBN tenants. The same IPv4 subnet.',1)
# Two rows keep the management connection distinct from the HBN data path.
text(M,488,'SSH PATH: nico-lab > Kubernetes helper pod > Ubuntu management IP',9,'Bold',MUTED)
for name,mgmt,host,vrf,vni,y in [('EUROPE','192.168.0.231','10.0.0.2/24','EUROPE','100001',472),('ASIA','192.168.0.232','10.0.0.1/24','ASIA','100002',409)]:
    box(M,y,310,54,colors.white)
    text(M+12,y-17,name+'  /  Ubuntu server',11,'Bold')
    text(M+12,y-34,'SSH '+mgmt+'   |   Data '+host,9)
    arrow(M+310,y-27,M+344,y-27)
    box(M+344,y,265,54,colors.white)
    text(M+356,y-17,'DPU / HBN  |  VRF '+vrf,10,'Bold')
    text(M+356,y-34,'Gateway 10.0.0.254  |  VNI '+vni,9)
    arrow(M+609,y-27,M+643,y-27)
    text(M+654,y-31,'Internet',11,'Bold',BLUE)
text(M,338,'Different VRFs and VNIs keep the two 10.0.0.0/24 networks isolated.',10,'Bold')
text(M,315,'1  Check readiness on nico-lab',12,'Bold')
code(M,304,W-2*M,READY)
paragraph(M,254,W-2*M,'Both DPUs must be Ready and Operational, HBN must be running, and the helper pod must be Ready. '
          'A missing Ubuntu data interface means the network demo is not ready.',9.3)
text(M,214,'2  Open Europe SSH from nico-lab',12,'Bold')
code(M,204,W-2*M,EUROPE)
text(M,134,'Open Asia SSH in a second nico-lab terminal',12,'Bold')
code(M,124,W-2*M,ASIA)
text(M,53,'Use your server SSH key or server password. The BMC password is a different credential.',9,color=MUTED)
c.showPage()
header('DEMO GUIDE / 02','Show Internet access and tenant isolation','Run these commands inside the Ubuntu SSH sessions from page 1.',2)
text(M,485,'3  Confirm the host address and default route',12,'Bold')
code(M,473,W-2*M,ADDRESS)
text(M,416,'Expected: Asia 10.0.0.1/24; Europe 10.0.0.2/24; gateway 10.0.0.254.',10,color=MUTED)
text(M,389,'4  Prove Internet access through HBN - run on both servers',12,'Bold')
code(M,377,W-2*M,INTERNET)
paragraph(M,311,W-2*M,'Expected: Cisco ping replies and successful HTTPS. The curl source must be '
          '<b>10.0.0.1</b> for Asia or <b>10.0.0.2</b> for Europe. '
          'Check that DATA_IF has the expected 10.0.0.x address before continuing.',9.5)
text(M,262,'5  Prove cross-tenant ping is blocked',12,'Bold')
text(M,239,'On Europe: ping Asia',10,'Bold')
code(M,228,W-2*M,PEER_EU)
text(M,178,'On Asia: ping Europe',10,'Bold')
code(M,167,W-2*M,PEER_AS)
paragraph(M,123,W-2*M,'Expected: <b>100% packet loss in both directions</b>, while step 4 succeeds on both hosts. '
          'A failed ping alone is not proof: an unfinished installation or a down interface also causes packet loss.',10)
text(M,67,'Present it: "Both servers reach the Internet, but their tenant data networks cannot ping each other."',10,'Bold')
text(M,50,'Monitor: tmux attach -t dpf-monitor   |   Ctrl+b then arrows: select pane   |   Ctrl+b then z: zoom',9,color=MUTED)
c.save()
# Plain text companion uses exactly the same command strings as the PDF.
(ROOT/'DPF-HBN-two-tenant-demo.txt').write_text(
    'DPF / HBN - EUROPE AND ASIA DEMO\n\n'
    '1. On nico-lab: verify both DPUs Ready/Operational, HBN running, and helper Ready.\n'+READY+'\n\n'
    '2. SSH from nico-lab (server credentials, not BMC credentials).\nEurope:\n'+EUROPE+'\n\nAsia:\n'+ASIA+'\n\n'
    '3. In each Ubuntu session: verify address and default route.\n'+ADDRESS+'\n'
    'Expected: Asia 10.0.0.1/24; Europe 10.0.0.2/24; gateway 10.0.0.254.\n\n'
    '4. Internet via HBN - run on BOTH Ubuntu servers.\n'+INTERNET+'\n'
    'Expect ping replies and HTTPS success with the matching 10.0.0.x source.\n\n'
    '5. Cross-tenant ICMP isolation.\nFrom Europe:\n'+PEER_EU+'\nFrom Asia:\n'+PEER_AS+'\n'
    'Expect 100% packet loss both ways ONLY after Internet checks succeed.\n'
    'An absent interface or unfinished installation is not isolation proof.\n\n'
    'Monitor: tmux attach -t dpf-monitor\nGuide: '+URL+'\n')
print(PDF)
