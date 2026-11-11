"""DPF-specific hardware inventory and explicitly selected storage write probe."""
import argparse
from decimal import Decimal
import json
import re
import signal
import subprocess
import sys
import time
import uuid

from nics import IMAGE
from prereq_status import read_json
from ui import banner,table,outcome


def quantity(value):
    match=re.fullmatch(r'([0-9.]+)([a-zA-Z]*)',str(value))
    if not match:raise ValueError('Unsupported Kubernetes quantity')
    units={'':1,'m':Decimal('0.001'),'Ki':1024,'Mi':1024**2,'Gi':1024**3,'Ti':1024**4,
           'k':1000,'M':1000**2,'G':1000**3,'T':1000**4}
    return Decimal(match[1])*units[match[2]]


def hardware_rows(nodes):
    rows=[]
    for node in nodes:
        labels=node['metadata'].get('labels',{})
        if not any(k in labels for k in ['node-role.kubernetes.io/control-plane','node-role.kubernetes.io/master']):continue
        status=node.get('status',{});capacity=status.get('capacity',{})
        cpu=quantity(capacity.get('cpu','0'));memory=quantity(capacity.get('memory','0'))
        architecture=status.get('nodeInfo',{}).get('architecture','Unknown')
        conditions={c['type']:c['status'] for c in status.get('conditions',[])}
        pressure=any(conditions.get(c) != 'False' for c in ['DiskPressure','MemoryPressure','PIDPressure'])
        ready=conditions.get('Ready')=='True'
        passed=cpu>=8 and memory>=16_000_000_000 and architecture in ('amd64','arm64') and not pressure and ready
        rows.append([node['metadata']['name'],str(cpu),f'{memory/Decimal(1024**3):.1f} GiB',architecture,
                     'Review' if pressure else 'Clear','PASS' if passed else 'Review'])
    return rows


def command(k,args,input=None):
    result=subprocess.run([*k,*args],input=input,text=True,capture_output=True,timeout=45)
    if result.returncode:raise RuntimeError('kubectl failed: '+result.stderr.strip())
    return result.stdout


def storage_objects(name,storage):
    return [
        {'apiVersion':'v1','kind':'Namespace','metadata':{'name':name}},
        {'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'probe','namespace':name},
         'spec':{'accessModes':['ReadWriteOnce'],'storageClassName':storage,'resources':{'requests':{'storage':'64Mi'}}}},
        {'apiVersion':'v1','kind':'Pod','metadata':{'name':'probe','namespace':name},
         'spec':{'automountServiceAccountToken':False,'restartPolicy':'Never','activeDeadlineSeconds':150,
                 'tolerations':[{'key':'node-role.kubernetes.io/control-plane','operator':'Exists','effect':'NoSchedule'},
                                {'key':'node-role.kubernetes.io/master','operator':'Exists','effect':'NoSchedule'}],
                 'securityContext':{'runAsNonRoot':True,'runAsUser':65534,'fsGroup':65534,'seccompProfile':{'type':'RuntimeDefault'}},
                 'containers':[{'name':'probe','image':IMAGE,'command':['sh','-c',
                     'set -eu; printf "dpf-storage-check" > /data/check; test "$(cat /data/check)" = dpf-storage-check; rm /data/check; echo STORAGE_READ_WRITE_OK'],
                     'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
                     'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'cpu':'100m','memory':'128Mi'}},
                     'volumeMounts':[{'name':'test','mountPath':'/data'}]}],
                 'volumes':[{'name':'test','persistentVolumeClaim':{'claimName':'probe'}}]}}
    ]


def storage_check(k,storage):
    sc=read_json([*k,'get','storageclass',storage,'-o','json'])
    if sc.get('reclaimPolicy','Delete')!='Delete':
        raise RuntimeError('Use a scratch StorageClass with Delete reclaim policy for this temporary write test.')
    name='dpf-sanity-'+uuid.uuid4().hex[:12]
    passed=False;created=False;volume=None
    try:
        objects=storage_objects(name,storage)
        command(k,['create','-f','-'],json.dumps(objects[0]));created=True
        for obj in objects[1:]:command(k,['create','-f','-'],json.dumps(obj))
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            pod=read_json([*k,'-n',name,'get','pod','probe','-o','json'])
            phase=pod.get('status',{}).get('phase')
            if phase=='Succeeded':
                claim=read_json([*k,'-n',name,'get','pvc','probe','-o','json'])
                volume=claim['spec'].get('volumeName')
                passed=claim.get('status',{}).get('phase')=='Bound' and bool(volume)
                break
            if phase=='Failed':
                print(command(k,['-n',name,'logs','probe']))
                raise RuntimeError('Storage write/read pod failed; inspect the unified log.')
            time.sleep(2)
        if not passed:raise RuntimeError('Storage probe did not complete within 180 seconds.')
        output=command(k,['-n',name,'logs','probe'])
        if 'STORAGE_READ_WRITE_OK' not in output:raise RuntimeError('Storage read/write result is missing.')
    finally:
        if created:
            # Read only this probe's claim, including when the pod failed.
            try:
                text=command(k,['-n',name,'get','pvc','probe','--ignore-not-found','-o','json'])
                if text.strip():volume=json.loads(text).get('spec',{}).get('volumeName')
            finally:
                command(k,['delete','namespace',name,'--ignore-not-found','--wait=true','--timeout=30s'])
                if volume and command(k,['get','pv',volume,'--ignore-not-found','-o','name']).strip():
                    command(k,['wait','--for=delete','pv/'+volume,'--timeout=30s'])
    table([[storage,'Bound','PASS','Complete']],['STORAGECLASS','PVC','READ / WRITE','CLEANUP'])
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['hardware','storage'])
    parser.add_argument('--context',required=True)
    parser.add_argument('--storage-class',default='local-path')
    args=parser.parse_args()
    k=['kubectl',f'--context={args.context}','--request-timeout=30s']
    banner('Sanity / '+args.mode,args.context)
    if args.mode=='storage':return storage_check(k,args.storage_class)
    rows=hardware_rows(read_json([*k,'get','nodes','-o','json'])['items'])
    table(rows,['CONTROL-PLANE NODE','CPU','MEMORY','ARCH','PRESSURE','RESULT'])
    print('\nDPF v26.4.0 minimum per control-plane machine: 8 CPUs, 16 GB RAM, amd64/arm64.')
    print('Capacity and node pressure only; not a measurement of free CPU, RAM or disk bytes.')
    return 0 if rows and all(r[-1]=='PASS' for r in rows) else 1


if __name__=='__main__':
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(143))
    try:sys.exit(main())
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
        outcome('blocked',str(error));sys.exit(1)
