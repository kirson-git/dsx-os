"""Compact terminal presentation; never emit ANSI escapes to redirected output."""
import os
import sys

CODES={'good':'0;32','warn':'0;33','bad':'0;31','info':'0;34','dim':'90','bold':'1'}


def color(text, tone='info'):
    enabled=sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    return f'\033[{CODES[tone]}m{text}\033[0m' if enabled else str(text)


def tone(value):
    value=str(value).lower()
    if value in {'ready','installed','deployed','match','accepted','configured','reused','pass','kept','keep','complete','succeeded'}:return 'good'
    if value in {'failed','blocked','not ready','auth failed','forbidden','tls error','timeout','unreachable','probe error'}:return 'bad'
    if value in {'missing','review','unknown','pending','untracked','unverified','repair','warn','remove','delete','wrong / no route'}:return 'warn'
    return None


def table(rows, headers):
    widths=[max(len(str(row[i])) for row in [headers,*rows]) for i in range(len(headers))]
    print('  '+color('  '.join(str(v).ljust(w) for v,w in zip(headers,widths)).rstrip(),'bold'))
    print('  '+color('  '.join('-'*w for w in widths),'dim'))
    for row in rows:
        cells=[]
        for value,width in zip(row,widths):
            cell=str(value).ljust(width)
            cells.append(color(cell,tone(value)) if tone(value) else cell)
        print('  '+'  '.join(cells).rstrip())


def banner(title, context=''):
    print('\n'+color('=== NICo + DPF Installer ===','info'))
    print(color('DPF Assistant | v26.4.0','info')+'  /  '+color(title))
    if context:print(color('Cluster: '+context,'dim'))
    print()


def outcome(state, message):
    label={'complete':'SUCCESS','ready':'SUCCESS','blocked':'ERROR','warn':'WARNING'}.get(state.lower(),state.upper())
    print('\n'+color('['+label+'] '+message,tone(state) or 'info'))


def menu(context):
    banner('Installation & diagnostics',context)
    rows=[
        ('1','Check environment','Installed, missing, versions and readiness'),
        ('2','Preview prerequisites','See what the installer will prepare'),
        ('3','Install prerequisites',"Install/reconcile NVIDIA's pinned charts"),
        ('4','Inspect node NICs','IP/subnet table using temporary diagnostic pods'),
        ('5','Collect DPF settings','Guided network, BMC, VIP and storage questionnaire'),
        ('6','Diagnose problems','Pod failures, unbound storage and warning events'),
        ('7','Installation guide','Show the manual DPF installation steps'),
        ('8','Clean','Reset DPF, CRDs and config; ask about storage'),
        ('9','Install DPF','Install v26.4.0 operator after prerequisite checks'),
        ('10','BMC setup and check','Choose node/NIC, BMC addresses and test access'),
        ('S','Sanity checks','Prerequisites, hardware or storage read/write'),
        ('L','Latest run logs','Exact commands, output and completion status'),
        ('M','More info','Cleanup / cluster diagnostic details'),
        ('0','Exit',''),
    ]
    for key,label,description in rows:
        print('  '+color(key.rjust(2),'info')+'  '+label.ljust(22)+' '+color(description,'dim'))


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='menu':menu(sys.argv[2] if len(sys.argv)>2 else '')
