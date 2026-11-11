"""Private installation history and transparent Helm/Helmfile/kubectl auditing."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

TOOLS=('helm','helmfile','kubectl')
OUTPUTS=('tools.log','bootstrap.log','datastore.log','install.log','repository.log','rollout.log')
SENSITIVE=re.compile(r'password|passwd|token|secret|credential|private.?key',re.I)


def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def redact(argv):
    result=[];hide=False
    for arg in argv:
        if hide:
            result.append('[REDACTED]');hide=False;continue
        if arg.startswith('--') and SENSITIVE.search(arg.split('=',1)[0]):
            if '=' in arg:result.append(arg.split('=',1)[0]+'=[REDACTED]')
            else:result.append(arg);hide=True
        elif '=' in arg and SENSITIVE.search(arg):
            result.append(arg.split('=',1)[0]+'=[REDACTED]')
        else:
            result.append(re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@',r'\1[REDACTED]@',arg))
    return result


def append(path,text):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    try:os.write(fd,text.encode())
    finally:os.close(fd)


def write_json(path,value):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
    temporary.write_text(json.dumps(value,indent=2)+'\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def start(base,run,action,context,legacy=False):
    base=base.resolve();run=run.resolve()
    root=base/'logs';root.mkdir(mode=0o700,exist_ok=True)
    logs=root/run.name
    logs.mkdir(mode=0o700,exist_ok=False)
    for name in OUTPUTS:
        (logs/name).symlink_to(os.path.relpath(run/name,logs))
    state={'action':action,'context':context,'run_directory':str(run),'started_at':now(),
           'started_epoch':time.time(),'state':'untracked' if legacy else 'running'}
    write_json(logs/'status.json',state)
    unified=root/('installation_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+run.name.rsplit('-',1)[-1]+'.log')
    append(unified,f'Installation started at {now()}\nAction: {action}\nContext: {context}\n')
    (logs/'installation.log').symlink_to(os.path.relpath(unified,logs))
    latest_file=root/('.latest-log-'+uuid.uuid4().hex)
    latest_file.symlink_to(unified.name)
    latest_file.replace(root/'latest.log')
    if legacy:
        append(unified,'Existing run: unified output and exact command history were not recorded. See phase logs in logs/latest/.\n')
        append(logs/'commands.log','# Existing run: exact commands were not recorded.\n# Output logs are linked without restarting the installation.\n')
    else:
        originals={tool:shutil.which(tool) for tool in TOOLS}
        write_json(logs/'tools.json',originals)
        bindir=run/'command-bin';bindir.mkdir(mode=0o700)
        for tool,original in originals.items():
            if not original:continue
            wrapper=bindir/tool
            wrapper.write_text('#!/bin/sh\nexec '+shlex.join([sys.executable,str(Path(__file__).resolve()),'proxy',tool])+' "$@"\n')
            wrapper.chmod(0o700)
        append(logs/'commands.log','# Actual tool invocations, in start order (nested Helmfile commands included).\n# Shell-quoted arguments; sensitive flags/URL credentials are redacted.\n# Each entry records cwd and selected execution environment. This is a log, not a replay script.\n')
    temporary=root/('.latest-'+uuid.uuid4().hex)
    temporary.symlink_to(logs.name)
    try:temporary.replace(root/'latest')
    finally:temporary.unlink(missing_ok=True)
    return logs


def finish(logs,code):
    state=json.loads((logs/'status.json').read_text())
    state.update(state='succeeded' if code==0 else 'failed',exit_code=code,finished_at=now(),
                 elapsed_seconds=round(time.time()-state['started_epoch'],1))
    write_json(logs/'status.json',state)
    append(logs/'installation.log',f'\nFinished at: {state["finished_at"]}\nResult: {state["state"].upper()} (exit code: {code})\n')


def message(text,level='INFO'):
    from ui import color
    level=level.upper()
    if level not in ('INFO','SUCCESS','WARNING','ERROR'):raise ValueError('Unknown log level')
    if os.environ.get('DPF_INSTALL_LOG'):
        append(Path(os.environ['DPF_INSTALL_LOG'])/'installation.log',f'[{now()}] [{level}] {text}\n')
    print(color(f'[{level}] {text}',{'SUCCESS':'good','WARNING':'warn','ERROR':'bad'}.get(level,'info')))


def phase(description, output, command, show_output=False):
    from ui import color
    logs=Path(os.environ['DPF_INSTALL_LOG'])
    unified=logs/'installation.log'
    line=f'\n\n==== {description} ====\nCommand: {shlex.join(redact(command))}\nExecuting at: {now()}\nOutput:\n'
    append(unified,line)
    print(color('[INFO] '+description,'info'),flush=True)
    started=time.monotonic();next_update=started+30
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    previous={}
    def stop(signum,_):
        if process.poll() is None:process.send_signal(signum)
    for sig in (signal.SIGINT,signal.SIGTERM):previous[sig]=signal.signal(sig,stop)
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    try:
        with output.open('ab') as raw:
            while selector.get_map():
                for key,_ in selector.select(timeout=1):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:selector.unregister(key.fileobj);continue
                    raw.write(chunk);raw.flush()
                    append(unified,chunk.decode('utf-8',errors='replace'))
                    if show_output:
                        sys.stdout.write(chunk.decode('utf-8',errors='replace'));sys.stdout.flush()
                if time.monotonic()>=next_update:
                    print(color(f'[INFO] {description} - {int(time.monotonic()-started)}s elapsed','info'),flush=True)
                    next_update=time.monotonic()+30
        code=process.wait();code=128-code if code<0 else code
    finally:
        selector.close()
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for sig,handler in previous.items():signal.signal(sig,handler)
    elapsed=round(time.monotonic()-started,1)
    result='SUCCESS' if code==0 else f'FAILED (exit code: {code})'
    append(unified,f'\nStatus: {result}\nElapsed: {elapsed}s\n')
    print(color(f'[{"SUCCESS" if code==0 else "ERROR"}] {description} ({elapsed}s)', 'good' if code==0 else 'bad'),flush=True)
    if code:print('Details: '+str(unified.resolve()),flush=True)
    return code


def proxy(tool,args):
    logs=Path(os.environ['DPF_INSTALL_LOG'])
    original=json.loads((logs/'tools.json').read_text())[tool]
    if not original:raise RuntimeError('Original tool unavailable: '+tool)
    argv=[original,*args];safe=redact(argv);ident=uuid.uuid4().hex[:12]
    env={key:os.environ[key] for key in ('KUBECONFIG','HELM_CONFIG_HOME','HELM_CACHE_HOME','HELM_DATA_HOME') if key in os.environ}
    event={'event':'start','id':ident,'timestamp':now(),'tool':tool,'argv':safe,'command':shlex.join(safe),
           'cwd':os.getcwd(),'environment':env}
    append(logs/'commands.jsonl',json.dumps(event)+'\n')
    append(logs/'commands.log',f'\n# {event["timestamp"]} id={ident}\n# cwd: {shlex.quote(event["cwd"])}\n'+
           ''.join('# '+key+'='+shlex.quote(value)+'\n' for key,value in env.items())+event['command']+'\n')
    append(logs/'installation.log',f'\n[{event["timestamp"]}] Command start id={ident}\nCommand: {event["command"]}\n')
    started=time.monotonic()
    process=subprocess.Popen(argv)
    def forward(signum,_):
        if process.poll() is None:process.send_signal(signum)
    signal.signal(signal.SIGTERM,forward)
    signal.signal(signal.SIGINT,forward)
    code=process.wait()
    code=128-code if code<0 else code
    append(logs/'commands.jsonl',json.dumps({'event':'end','id':ident,'timestamp':now(),'exit_code':code,
                                           'elapsed_seconds':round(time.monotonic()-started,3)})+'\n')
    completed=now()
    append(logs/'commands.log',f'# {completed} id={ident} exit={code}\n')
    append(logs/'installation.log',f'\n[{completed}] Command end id={ident} exit={code}\n')
    return code


def show(base):
    from ui import banner,table
    latest=base/'logs/latest'
    banner('Latest run logs')
    if not latest.is_dir():print('No installation logs yet.');return
    state=json.loads((latest/'status.json').read_text())
    table([[state['action'],state['state'],state.get('exit_code','-'),(str(state['elapsed_seconds'])+'s' if 'elapsed_seconds' in state else '-')]],
          ['ACTION','STATUS','EXIT','ELAPSED'])
    print('\n'+str(latest.resolve()))
    print('  installation.log  Unified step-by-step output (also logs/latest.log)')
    print('  commands.log    '+('History unavailable for this older run' if state['state']=='untracked' else 'Exact tool commands, timestamps and exit codes'))
    for name in OUTPUTS:
        if (latest/name).exists():print('  '+name)
    if state['state']=='untracked':print('This run predates command recording; only its existing output is available.')


def main():
    if len(sys.argv)==4 and sys.argv[1]=='message':
        message(sys.argv[3],sys.argv[2]);return 0
    if len(sys.argv)>2 and sys.argv[1]=='proxy':return proxy(sys.argv[2],sys.argv[3:])
    if len(sys.argv)>4 and sys.argv[1]=='phase':
        args=sys.argv[2:];show=args[0]=='--show-output'
        if show:args=args[1:]
        return phase(args[0],Path(args[1]),args[2:],show)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','finish','show'])
    parser.add_argument('--base',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--run',type=Path)
    parser.add_argument('--kind',default='prerequisites')
    parser.add_argument('--context',default='')
    parser.add_argument('--legacy',action='store_true')
    parser.add_argument('--logs',type=Path)
    parser.add_argument('--exit-code',type=int)
    args=parser.parse_args()
    if args.action=='start':
        if args.run is None:parser.error('--run required')
        print(start(args.base,args.run,args.kind,args.context,args.legacy))
    elif args.action=='finish':
        if args.logs is None or args.exit_code is None:parser.error('--logs and --exit-code required')
        finish(args.logs,args.exit_code)
    else:show(args.base)
    return 0


if __name__=='__main__':sys.exit(main())
