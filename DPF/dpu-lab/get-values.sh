#!/usr/bin/env bash
# Print the values you need for the files in dpu-lab/, read from the live systems.
# It only reads. It changes nothing and prints no password.
#
#   bash dpu-lab/get-values.sh                              # cluster, DPU cards, BGP state
#   bash dpu-lab/get-values.sh --bmc 192.0.2.246            # name the DPU BMC yourself
#   bash dpu-lab/get-values.sh --switch cumulus@192.0.2.254 # also read the switch (ssh asks for its password)
set -u

NS=dpf-operator-system
BMC=""; SW=""
while [ $# -gt 0 ]; do
  case "$1" in
    --bmc) BMC="${2:-}"; shift 2 ;;
    --switch) SW="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
done

k() { kubectl --request-timeout=20s "$@" </dev/null 2>/dev/null; }
row() { printf '  %-22s %-34s %s\n' "$1" "$2" "$3"; }
head1() { printf '\n== %s\n' "$1"; }

# ---------- 1. management cluster ----------
head1 "1. Management cluster  (file 1-dpf-settings/operatorconfig.yaml)"
CTX=$(k config current-context)
API=$(k config view --minify -o jsonpath='{.clusters[0].cluster.server}')
API_HOST=${API#https://}; API_HOST=${API_HOST%%:*}
# The kubeconfig may name a node instead of an address: the file needs the address.
API_IP=$(k get node "$API_HOST" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
[ -n "$API_IP" ] && API_HOST="$API_IP"
row "kubectl context" "${CTX:-not found}" ""
row "API address" "${API_HOST:-not found}" "-> kubernetesAPIServerVIP"
row "API port" "${API##*:}" "-> kubernetesAPIServerPort"
echo "  Management nodes (the VIP interface must exist on each of them):"
k get nodes -o jsonpath='{range .items[*]}{"    "}{.metadata.name}{"  "}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'

# ---------- 2. DPU card, read from its BMC ----------
head1 "2. DPU card  (file 4-dpu-install/dpudevice.yaml)"
[ -n "$BMC" ] || BMC=$(k get dpudevice -n "$NS" -o jsonpath='{range .items[*]}{.spec.bmcIp}{"\n"}{end}')
[ -n "$BMC" ] || echo "  No DPU BMC address known. Run again with: --bmc <address of the DPU BMC>"
for BMC in $BMC; do
  row "DPU BMC address" "$BMC" "-> bmcIp and label dpudevice-bmc-ip"
  PW=$(k get secret bmc-shared-password -n "$NS" -o jsonpath='{.data.password}' | base64 -d 2>/dev/null)
  if [ -z "$PW" ]; then
    echo "  The Secret bmc-shared-password does not exist yet (README step 2)."
    echo "  Until then, this command asks for the BMC password and prints both values:"
    echo "    curl -sk --user root https://$BMC/redfish/v1/Systems/Bluefield | grep -oE '\"(SerialNumber|PartNumber)\": *\"[^\"]*\"'"
  else
    # The password goes to python on standard input, so it never shows in the process list.
    printf '%s' "$PW" | python3 -I -c '
import base64, json, ssl, sys, urllib.request
bmc = sys.argv[1]; pw = sys.stdin.read()
req = urllib.request.Request("https://%s/redfish/v1/Systems/Bluefield" % bmc)
req.add_header("Authorization", "Basic " + base64.b64encode(("root:" + pw).encode()).decode())
try:
    d = json.load(urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=20))
except Exception as e:
    print("  The BMC did not answer the request: %s %s" % (type(e).__name__, getattr(e, "code", ""))); sys.exit(0)
fmt = "  %-22s %-34s %s"
print(fmt % ("serial number", d.get("SerialNumber", "not reported"), "-> serialNumber and label dpudevice-psid"))
print(fmt % ("part number (OPN)", d.get("PartNumber", "not reported"), "-> opn and label dpudevice-opn"))
print(fmt % ("model", d.get("Model", "not reported"), ""))
' "$BMC"
  fi
done

# ---------- 3. after the install: DPU state and HBN BGP ----------
head1 "3. After the install: DPU and HBN BGP"
DPUS=$(k get dpu -n "$NS" -o jsonpath='{range .items[*]}{.metadata.name}{"  phase="}{.status.phase}{"\n"}{end}')
if [ -z "$DPUS" ]; then
  echo "  No DPU object yet. This part works after README step 6."
else
  printf '%s\n' "$DPUS" | sed 's/^/  /'
  TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT; chmod 600 "$TMP"
  for CL in $(k get dpucluster -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"/"}{.metadata.name}{"\n"}{end}'); do
  CNS=${CL%%/*}; CNAME=${CL##*/}
  echo "  DPU cluster $CNAME:"
  PORT=$(k get svc "$CNAME" -n "$CNS" -o jsonpath='{.spec.ports[0].nodePort}')
  NODEIP=$(k get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
  k get secret "$CNAME-admin-kubeconfig" -n "$CNS" -o jsonpath='{.data.admin\.conf}' | base64 -d > "$TMP" 2>/dev/null
  VIP=$(kubectl --kubeconfig "$TMP" config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null)
  VIP=${VIP#https://}; VIP=${VIP%%:*}
  if [ -z "$PORT" ] || [ -z "$VIP" ]; then
    echo "  Could not find the DPU cluster API (cluster '$CNAME'). BGP not checked."
  else
    # The admin host may not reach the cluster VIP, so go through a management node port.
    dk() { kubectl --kubeconfig "$TMP" --server "https://$NODEIP:$PORT" --tls-server-name "$VIP" --request-timeout=30s "$@" </dev/null 2>/dev/null; }
    PODS=$(dk get pods -n "$NS" -l app.kubernetes.io/name=hbn -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
    [ -n "$PODS" ] || echo "  No HBN pod found in the DPU cluster yet."
    for POD in $PODS; do
      echo "  HBN pod $POD:"
      OUT=$(dk exec "$POD" -n "$NS" -c doca-hbn -- vtysh -c 'show bgp ipv4 unicast summary')
      printf '%s\n' "$OUT" | grep -E 'local AS number' | sed -E 's/.*(local AS number [0-9]+).*/    \1  (bgp_autonomous_system in 3-hbn-network\/hbn-config.yaml)/'
      printf '%s\n' "$OUT" | grep -E '^Neighbor|_if\)' | cut -c1-110 | sed 's/^/    /'
      TOTAL=$(printf '%s\n' "$OUT" | grep -cE '_if\)')
      DOWN=$(printf '%s\n' "$OUT" | grep -E '_if\)' | grep -cE 'Idle|Active|Connect|OpenSent|OpenConfirm|never')
      if [ "$TOTAL" -eq 0 ]; then echo "    RESULT: no BGP neighbor configured."
      elif [ "$DOWN" -eq 0 ]; then echo "    RESULT: OK, $TOTAL of $TOTAL BGP sessions to the switch are up."
      else echo "    RESULT: NOT OK, $DOWN of $TOTAL BGP sessions are down. Compare the AS number above with remote-as on the switch (part 4)."
      fi
      # The server takes the first address of the host block; HBN holds the gateway on pf0hpf_if.
      GWCIDR=$(dk exec "$POD" -n "$NS" -c doca-hbn -- ip -o -4 addr show pf0hpf_if | sed -E 's/.* inet ([0-9./]+).*/\1/')
      VRF=$(dk exec "$POD" -n "$NS" -c doca-hbn -- ip -o link show pf0hpf_if | sed -nE 's/.* master ([^ ]+).*/\1/p')
      SRV=$(python3 -I -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network.network_address + 1)' "$GWCIDR" 2>/dev/null)
      if [ -n "$SRV" ] && [ -n "$VRF" ]; then
        if dk exec "$POD" -n "$NS" -c doca-hbn -- ip vrf exec "$VRF" ping -c 2 -W 2 "$SRV" >/dev/null; then
          echo "    SERVER: OK, the server address $SRV answers from HBN (gateway ${GWCIDR%%/*}, VRF $VRF)."
        else
          echo "    SERVER: no answer from $SRV. Set this address on the server port that connects to the DPU (README step 10)."
        fi
      fi
    done
  fi
  done
fi

# ---------- 4. values that live on the switch ----------
head1 "4. Values that must match the switch  (file 3-hbn-network/hbn-config.yaml)"
if [ -n "$SW" ]; then
  echo "  Reading the switch $SW (read-only; ssh may ask for the password):"
  # GET_VALUES_SSH_OPTS can hold extra ssh options, for example a known-hosts file.
  # shellcheck disable=SC2086,SC2029
  ssh -o ConnectTimeout=10 ${GET_VALUES_SSH_OPTS:-} "$SW" "
    echo '  -- ports: which switch port sees which neighbour (the name of your DPU shows its ports)'
    nv show interface lldp 2>&1 | grep -E 'Interface|swp' | sed -E 's/([0-9a-f]{2}:){5}[0-9a-f]{2}/(port MAC)/; s/^/     /'
    echo '  -- the switch configuration lines that your values must match'
    echo '     (ASN = remote-as of the peer group of your ports; VRF and L3VNI = evpn vni; LOOPBACK = prefix-list match)'
    nv config show -o commands 2>&1 | grep -E 'router bgp autonomous-system|neighbor swp[0-9]+ peer-group|peer-group [^ ]+ remote-as|peer-group [^ ]+ address-family ipv4-unicast policy inbound|evpn vni|prefix-list [^ ]+ rule [0-9]+ match|route-target' | sed 's/^/     /'
  " </dev/null || echo "  Could not read the switch. Check the address and the user."
else
  echo "  No switch was named. Either run this script again with  --switch <user@switch-address>,"
  echo "  or run these two commands on the switch yourself:"
  echo
  echo "    nv config show | grep -B4 \"'[0-9][0-9][0-9][0-9]*': {}\""
  echo "        each VRF name, and 4 lines below it its VNI     -> VRF and L3VNI"
  echo "    nv config show | grep -n -B12 remote-as"
  echo "        remote-as of the peer group of your DPU ports   -> ASN"
  echo
  echo "  The host block (HOST_NET) and the loopback (LOOPBACK) are chosen by the site owner."
  echo "  The switch must permit the loopback in its inbound prefix list, or VXLAN does not work."
fi
