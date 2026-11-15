#!/usr/bin/env bash
# Open a shell on the server that holds a DPU, when that server has no management address.
# The login goes through the HBN pod on the DPU of that tenant:
# admin host -> DPU cluster API -> HBN pod (tenant VRF) -> IPv6 link-local address of the server port.
#
#   bash dpu-lab/server-login.sh lab                   # server of the first tenant, interactive
#   bash dpu-lab/server-login.sh asia 'ip -br addr'    # run one command on the server of tenant asia
#   bash dpu-lab/server-login.sh lab 'cat > server-address.sh' < dpu-lab/server-address.sh   # copy a file
#
# The tenant name is the name inside the objects: "lab" for the first tenant.
# SERVER_USER (default: ubuntu) and SERVER_KEY (path of an ssh private key) set the login.
# It needs the DPU to be Ready and the server to be powered on.
set -euo pipefail
[ $# -ge 1 ] || { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
T=$1; shift
NS=dpf-operator-system
KCFG=$(mktemp); chmod 600 "$KCFG"; PROXY=$(mktemp); chmod 700 "$PROXY"
trap 'rm -f "$KCFG" "$PROXY"' EXIT
kubectl -n "dpu-cluster-$T" get secret "dpu-cluster-$T-admin-kubeconfig" -o jsonpath='{.data.admin\.conf}' </dev/null 2>/dev/null | base64 -d > "$KCFG"
[ -s "$KCFG" ] || { echo "STOP: no DPU cluster named dpu-cluster-$T"; exit 1; }
# The admin host may not reach the cluster VIP, so go through a management node port.
PORT=$(kubectl -n "dpu-cluster-$T" get svc "dpu-cluster-$T" -o jsonpath='{.spec.ports[0].nodePort}' </dev/null)
NODEIP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' </dev/null)
VIP=$(kubectl --kubeconfig "$KCFG" config view --minify -o jsonpath='{.clusters[0].cluster.server}'); VIP=${VIP#https://}; VIP=${VIP%%:*}
DK="kubectl --kubeconfig $KCFG --server https://$NODEIP:$PORT --tls-server-name $VIP -n $NS"
POD=$($DK get pods -l app.kubernetes.io/name=hbn -o jsonpath='{.items[0].metadata.name}' </dev/null)
[ -n "$POD" ] || { echo "STOP: no HBN pod in dpu-cluster-$T yet"; exit 1; }
VRF=$($DK exec "$POD" -c doca-hbn -- ip -o link show pf0hpf_if </dev/null | sed -nE 's/.* master ([^ ]+).*/\1/p')
# The server port is the only other station on pf0hpf_if: it answers the all-nodes ping.
SERVER_LL=$($DK exec "$POD" -c doca-hbn -- ip vrf exec "$VRF" ping -6 -c 2 -W 2 "ff02::1%pf0hpf_if" </dev/null 2>/dev/null \
  | sed -nE 's/.*from (fe80:[0-9a-f:]+)%.*/\1/p' | head -1)
[ -n "$SERVER_LL" ] || { echo "STOP: the server of tenant $T does not answer on the DPU port (is it powered on?)"; exit 1; }
cat > "$PROXY" <<PROXYEOF
#!/bin/bash
exec $DK exec -i $POD -c doca-hbn -- ip vrf exec $VRF python3 -u -c '
import os, select, socket
s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
s.connect(("$SERVER_LL", 22, 0, socket.if_nametoindex("pf0hpf_if")))
while True:
    r, _, _ = select.select([s, 0], [], [])
    if s in r:
        d = s.recv(65536)
        if not d: break
        os.write(1, d)
    if 0 in r:
        d = os.read(0, 65536)
        if not d: break
        s.sendall(d)
'
PROXYEOF
KEY=(); [ -z "${SERVER_KEY:-}" ] || KEY=(-i "$SERVER_KEY" -o IdentitiesOnly=yes)
# The host key of each server is saved on first use under the name server-<tenant>.
ssh "${KEY[@]}" -o ProxyCommand="$PROXY" -o HostKeyAlias="server-$T" -o StrictHostKeyChecking=accept-new \
  "${SERVER_USER:-ubuntu}@server-behind-dpu" "$@"
