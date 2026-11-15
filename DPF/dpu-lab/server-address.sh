#!/usr/bin/env bash
# Run this ON THE SERVER that holds the DPU, as root. It gives the server port that
# connects to the DPU a permanent address, gateway and DNS servers (netplan).
#
#   sudo bash server-address.sh <port> <address/prefix> <gateway> <dns,dns> [--check]
#   sudo bash server-address.sh enp23s0f0np0 10.60.126.1/29 10.60.126.2 203.0.113.53,203.0.113.54
#
# --check only validates and prints the file; it changes nothing.
# Safe to try: if the gateway does not answer after the change, the change is undone
# by itself after 3 minutes. It writes one file: /etc/netplan/60-dpu-port.yaml.
set -euo pipefail

stop() { echo "STOP: $*"; exit 1; }
[ $# -ge 4 ] || { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
PORT=$1; ADDR=$2; GW=$3; DNS=$4; CHECK=${5:-}
[ "$(id -u)" = 0 ] || stop "run it with sudo"
[ -e "/sys/class/net/$PORT" ] || stop "port $PORT does not exist on this server (see: ip -br link)"
case "$ADDR" in */*) ;; *) stop "the address needs a prefix, for example 10.60.126.1/29" ;; esac

FILE=/etc/netplan/60-dpu-port.yaml
WORK=$(mktemp -d /var/tmp/dpu-port.XXXXXX); chmod 700 "$WORK"
mkdir -p "$WORK/staged/etc/netplan"
cp -a /etc/netplan/*.yaml "$WORK/staged/etc/netplan/" 2>/dev/null || true

# If a netplan file already describes this port (for example the cloud-init file, which matches
# it by MAC address and asks for DHCP), the new file must use the same name for it. Netplan then
# merges both, and the values here win. With another name the old DHCP setting would win.
ID=$(python3 - "$PORT" <<'PY'
import glob, sys, yaml
port = sys.argv[1]; mac = open('/sys/class/net/%s/address' % port).read().strip().lower()
found = port
for f in sorted(glob.glob('/etc/netplan/*.yaml')):
    if f.endswith('/60-dpu-port.yaml'): continue
    try: eth = (yaml.safe_load(open(f)) or {}).get('network', {}).get('ethernets', {}) or {}
    except Exception: continue
    for name, cfg in eth.items():
        m = (cfg or {}).get('match', {}) or {}
        if name == port or m.get('name') == port or str(m.get('macaddress', '')).lower() == mac: found = name
print(found)
PY
)
[ "$ID" = "$PORT" ] || echo "Note: an existing netplan file calls this port \"$ID\"; using that name."

{
  echo "# Written by server-address.sh: the server port that connects to the DPU."
  echo "network:"
  echo "  version: 2"
  echo "  renderer: networkd"
  echo "  ethernets:"
  echo "    $ID:"
  echo "      dhcp4: false"
  echo "      dhcp6: false"
  echo "      accept-ra: false"
  echo "      addresses:"
  echo "        - $ADDR"
  echo "      mtu: 1500"
  echo "      nameservers:"
  echo "        addresses:"
  for d in ${DNS//,/ }; do echo "          - $d"; done
  echo "      routes:"
  echo "        - to: default"
  echo "          via: $GW"
} > "$WORK/staged/etc/netplan/60-dpu-port.yaml"
chmod 600 "$WORK/staged/etc/netplan/60-dpu-port.yaml"

# netplan checks the new file together with the files that already exist.
netplan generate --root-dir "$WORK/staged" || { rm -rf "$WORK"; stop "netplan refused the file. Nothing was changed."; }
if [ "$CHECK" = "--check" ]; then
  cat "$WORK/staged/etc/netplan/60-dpu-port.yaml"; rm -rf "$WORK"
  echo "CHECK OK: the file is valid. Nothing was changed."; exit 0
fi

# The way back, started by a timer unless the gateway answers.
[ -e "$FILE" ] && cp -a "$FILE" "$WORK/before.yaml"
cat > "$WORK/rollback.sh" <<ROLLBACK
#!/usr/bin/env bash
if [ -e "$WORK/before.yaml" ]; then install -m 600 "$WORK/before.yaml" "$FILE"; else rm -f "$FILE"; fi
netplan apply
ROLLBACK
chmod 700 "$WORK/rollback.sh"
UNIT="dpu-port-rollback-$$"
systemd-run --quiet --unit="$UNIT" --on-active=3m /usr/bin/bash "$WORK/rollback.sh"

install -m 600 "$WORK/staged/etc/netplan/60-dpu-port.yaml" "$FILE"
netplan apply
# The port needs a few seconds to take the address.
for _ in 1 2 3 4 5 6 7 8; do ping -c 1 -W 2 "$GW" >/dev/null 2>&1 && break; sleep 3; done
if ping -c 3 -W 2 "$GW" >/dev/null 2>&1; then
  systemctl stop "$UNIT.timer"
  echo "OK: $PORT has $ADDR, the gateway $GW answers, and the setting is permanent ($FILE)."
  echo "The copy of the old state is in $WORK."
else
  echo "NOT OK: the gateway $GW does not answer. The change is undone by itself in 3 minutes."
  exit 1
fi
