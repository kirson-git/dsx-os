#!/usr/bin/env bash
# Standalone Bash entrypoint; Python handles private files and helper-pod input.
set +x
set -euo pipefail
umask 077
command -v python3 >/dev/null || { echo 'Install Python 3 first.' >&2; exit 1; }
export DSX_CREDENTIAL_SCRIPT_DIR
DSX_CREDENTIAL_SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 - "$@" <<'PY'
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import uuid

IMAGE = 'docker.io/nicolaka/netshoot@sha256:a20c2531bf35436ed3766cd6cfe89d352b050ccc4d7005ce6400adf97503da1b'
NS = 'dpf-operator-system'
PROBE = r'''
import base64,json,os,subprocess,sys,tempfile
from pathlib import Path
results=[]
for t in json.load(sys.stdin):
    ok=False; detail='probe failed'
    try:
        if t['kind']=='ssh':
            with tempfile.TemporaryDirectory() as temp:
                p=Path(temp); (p/'known').write_text(t['knownHosts']); (p/'known').chmod(0o600)
                (p/'askpass').write_text('#!/bin/sh\nprintf "%s\\n" "$DSX_SSH_PASSWORD"\n'); (p/'askpass').chmod(0o700)
                env=dict(os.environ,SSH_ASKPASS=str(p/'askpass'),SSH_ASKPASS_REQUIRE='force',DISPLAY=':0',DSX_SSH_PASSWORD=t['password'])
                r=subprocess.run(['ssh','-F','/dev/null','-o','ConnectTimeout=5','-o','ConnectionAttempts=1','-o','NumberOfPasswordPrompts=1','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(p/'known'),'-o','GlobalKnownHostsFile=/dev/null','-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','LogLevel=ERROR','-l',t['username'],t['ip'],'true'],stdin=subprocess.DEVNULL,capture_output=True,env=env,start_new_session=True,timeout=20)
                ok=r.returncode==0;detail='SSH login passed' if ok else 'SSH failed: check reachability, host key and credentials'
        else:
            token=base64.b64encode((t['username']+':'+t['password']).encode()).decode()
            cmd=['curl','--silent','--show-error','--noproxy','*','--proto','=https','--connect-timeout','5','--max-time','20','--max-filesize','1048576','--config','-','--write-out','\n%{http_code}']
            if not t['verifyTLS']:cmd+=['--insecure']
            cmd+=['https://'+t['ip']+'/redfish/v1/Systems/Bluefield']
            r=subprocess.run(cmd,input='header = "Authorization: Basic '+token+'"\n',capture_output=True,text=True,timeout=25)
            detail='network/TLS failure'
            if r.returncode==60:detail='TLS verification failed (self-signed lab: --insecure-bmc)'
            elif r.returncode in (7,28):detail='unreachable or timed out'
            elif r.returncode==0:
                body,_,code=r.stdout.rpartition('\n')
                detail='HTTP '+code
                if code=='200':
                    identity=json.loads(body)
                    ok=isinstance(identity,dict) and bool(identity.get('SerialNumber'))
                    detail='BMC login passed; BlueField identity returned' if ok else 'unexpected device response'
                elif code in ('401','403'):detail='BMC authentication denied'
    except Exception:
        detail='probe could not complete'
    results.append({'name':t['name'],'ok':ok,'detail':detail})
print(json.dumps(results))
'''


def in_git(path):
    repo=Path(os.environ['DSX_CREDENTIAL_SCRIPT_DIR']).parent.resolve()
    return (repo/'.git').exists() and repo in (path, *path.parents)


def private_text(filename):
    path=Path(filename)
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) not in (0o400,0o600):
        raise ValueError('Credential files must be regular files with mode 600/400')
    if in_git(path.resolve().parent):
        raise ValueError('Credential files must be outside Git')
    text=path.read_text()
    if not text or '\x00' in text or '\r' in text:
        raise ValueError('Credential files must be nonempty, without NUL or CR characters')
    return text


def credentials(filename):
    data={}
    for line in private_text(filename).splitlines():
        key,sep,value=line.partition('=')
        if not sep or key not in ('username','password') or key in data or not value:
            raise ValueError('Use exactly two literal lines: username=USER and password=PASSWORD (no quotes)')
        data[key]=value
    if set(data)!= {'username','password'} or any(c in data['username'] for c in ':\n\r'):
        raise ValueError('Credential file must include username and password')
    return data


def addresses(value):
    if value is None:return []
    parts=value.split(',')
    result=[str(ipaddress.IPv4Address(p)) for p in parts]
    if len(result)>32 or len(set(result))!=len(result):
        raise ValueError('Supply 1–32 unique IPv4 addresses separated by commas')
    return result


def kube(args,payload=None,timeout=45):
    try:
        r=subprocess.run(['kubectl','--request-timeout=30s',*args],input=payload,capture_output=True,text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):
        raise RuntimeError('kubectl failed or timed out; no credential output displayed') from None
    if r.returncode:
        raise RuntimeError('kubectl operation failed; check context, RBAC and helper pod events (response hidden)')
    return r.stdout


def main():
    parser=argparse.ArgumentParser(prog='credentials.sh', description='Check DPU BMC credentials from a temporary Kubernetes pod, then save the DPF Secret. No password prompts.',epilog='Files: username=USER and password=PASSWORD on separate literal lines, mode 600/400, outside Git. Requires kubectl and Python 3. Namespace dpf-operator-system must exist. Does not reboot hardware or change account passwords.')
    files=parser.add_mutually_exclusive_group(required=True)
    files.add_argument('--bmc-pass',metavar='FILE',help='BMC username/password file; DPF requires username=root')
    files.add_argument('--password-file',metavar='FILE',help='Legacy password-only file, no newline; username=root')
    parser.add_argument('--ip',help='Comma-separated DPU BMC IPv4 addresses (not DPU OS SSH IPs)')
    parser.add_argument('--dpu-pass',metavar='FILE',help='Optional DPU OS SSH username/password file')
    parser.add_argument('--dpu-ip',help='Comma-separated DPU OS SSH IPv4 addresses; separate from BMC IPs')
    parser.add_argument('--ssh-known-hosts',metavar='FILE',help='Verified SSH known_hosts; required for SSH checks')
    parser.add_argument('--node',help='Optional management Kubernetes node that can reach the BMC/DPU network')
    parser.add_argument('--insecure-bmc',action='store_true',help='Explicitly disable BMC TLS verification for a self-signed lab')
    parser.add_argument('--check-only',action='store_true',help='Validate without saving a Secret')
    parser.add_argument('--skip-check',action='store_true',help='Advanced: save only after separate validation; used by bootstrap-credentials.sh')
    args=parser.parse_args()
    def interrupted(signum,frame): raise KeyboardInterrupt
    for signum in (signal.SIGTERM,signal.SIGHUP):signal.signal(signum,interrupted)
    try:
        ips=addresses(args.ip); ssh_ips=addresses(args.dpu_ip)
        if args.skip_check and (ips or ssh_ips or args.dpu_pass or args.ssh_known_hosts or args.check_only):
            raise ValueError('--skip-check cannot be combined with validation options')
        if not args.skip_check and not ips:raise ValueError('--ip is required for BMC validation')
        if args.node and not re.fullmatch(r'[a-z0-9]([a-z0-9.-]*[a-z0-9])?',args.node):raise ValueError('Invalid --node')
        if bool(args.dpu_pass) != bool(ssh_ips) or bool(args.ssh_known_hosts) != bool(ssh_ips):
            raise ValueError('SSH validation requires --dpu-pass, --dpu-ip and --ssh-known-hosts together')
        if args.bmc_pass:bmc=credentials(args.bmc_pass)
        else:
            password=private_text(args.password_file)
            if '\n' in password:raise ValueError('Legacy password-only files must contain no newline')
            bmc={'username':'root','password':password}
        if bmc['username']!='root':raise ValueError('DPF shared BMC Secret uses the root account; other usernames are unsupported')
        targets=[dict(name='BMC '+ip,kind='redfish',ip=ip,verifyTLS=not args.insecure_bmc,**bmc) for ip in ips]
        if ssh_ips:
            ssh=credentials(args.dpu_pass); known=Path(args.ssh_known_hosts).read_text()
            if not known.strip():raise ValueError('SSH known_hosts must contain verified host keys')
            targets += [dict(name='DPU SSH '+ip,kind='ssh',ip=ip,knownHosts=known,**ssh) for ip in ssh_ips]
        temp_root=Path(tempfile.gettempdir()).resolve()
        if in_git(temp_root):raise ValueError('Temporary directory must be outside Git')
        with tempfile.TemporaryDirectory(prefix='dsx-credentials-',dir=temp_root) as temp:
            config=Path(temp)/'kubeconfig'
            config.write_text(kube(['config','view','--raw','--minify','--flatten','-o','json']))
            config.chmod(0o600); os.environ['KUBECONFIG']=str(config)
            kube(['get','namespace',NS])
            pod='dpf-bmc-check-'+uuid.uuid4().hex[:10]
            created=False
            try:
                if not args.skip_check:
                    if args.insecure_bmc:print('BMC TLS verification disabled for this lab check.',flush=True)
                    print('Checking from helper pod '+pod,flush=True)
                    spec={'hostNetwork':True,'dnsPolicy':'ClusterFirstWithHostNet','automountServiceAccountToken':False,'restartPolicy':'Never','activeDeadlineSeconds':1800,'containers':[{'name':'check','image':IMAGE,'command':['sleep','1800'],'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'memory':'256Mi'}}}]}
                    if args.node:spec['nodeName']=args.node
                    created=True
                    kube(['create','-f','-'],json.dumps({'apiVersion':'v1','kind':'Pod','metadata':{'name':pod,'namespace':NS},'spec':spec}))
                    kube(['-n',NS,'wait','pod/'+pod,'--for=condition=Ready','--timeout=180s'],timeout=190)
                    # Credentials travel only over exec stdin, never argv, env or pod specs.
                    results=json.loads(kube(['-n',NS,'exec','-i',pod,'--','python3','-c',PROBE],json.dumps(targets),timeout=30*len(targets)+15))
                    if not isinstance(results,list) or len(results)!=len(targets):raise RuntimeError('Incomplete validation results')
                    for target,result in zip(targets,results):
                        if not isinstance(result,dict) or result.get('name')!=target['name'] or type(result.get('ok')) is not bool:raise RuntimeError('Invalid validation results')
                        print(('PASS ' if result['ok'] else 'FAIL ')+target['name']+': '+result['detail'],flush=True)
                    if not all(r['ok'] for r in results):raise RuntimeError('Credential check failed; existing Secret unchanged')
                    if not ssh_ips:print('DPU OS SSH not checked (optional; not required for BFB provisioning).',flush=True)
                else:print('Skipping checks: caller must have validated these credentials separately.',flush=True)
                if args.check_only:
                    print('Checks passed; no Secret changed.');return
                secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'bmc-shared-password','namespace':NS},'type':'Opaque','data':{'password':base64.b64encode(bmc['password'].encode()).decode()}}
                kube(['apply','--server-side','--field-manager=dsx-private-credentials','-f','-'],json.dumps(secret))
                print('Saved Secret dpf-operator-system/bmc-shared-password; value hidden.',flush=True)
            finally:
                if created:
                    try:kube(['-n',NS,'delete','pod',pod,'--ignore-not-found','--wait=false'])
                    except RuntimeError:print('Helper cleanup failed; remove pod '+pod+' in '+NS+'.',file=sys.stderr)
    except KeyboardInterrupt:
        parser.exit(130,'Interrupted; credential output hidden.\n')
    except (ValueError,OSError,RuntimeError,KeyError) as error:
        # Never emit endpoint responses, subprocess stderr or credential parse data.
        message=str(error) if type(error) is RuntimeError else 'Invalid inputs; check file format, permissions, IPs and required options (--help).'
        parser.exit(1,'ERROR: '+message+'\n')

main()
PY
