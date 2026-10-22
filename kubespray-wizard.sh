#!/usr/bin/env bash
#
# Interactive, key-only Kubespray inventory builder and deployment launcher.
# It never accepts or stores SSH passwords.

set -euo pipefail
umask 077

PROJECT_ROOT="$(pwd -P)"
INVENTORY_ROOT="$PROJECT_ROOT/infra/kubespray/inventories"

KUBESPRAY_TAG="v2.31.0"
KUBESPRAY_COMMIT="1c9add48975060f45396b34d8e022c30d7f80dab"
KUBESPRAY_IMAGE_DIGEST="sha256:6ecdd749a3661c44656ea66d9cff22bbd0b58e3d6122b59ec52ddaaa677f919d"
KUBESPRAY_IMAGE="quay.io/kubespray/kubespray@${KUBESPRAY_IMAGE_DIGEST}"

KUBE_VERSION="1.35.4"
CONTAINERD_VERSION="2.2.3"
CALICO_VERSION="v3.31.5"
DEFAULT_POD_CIDR="10.233.64.0/18"
DEFAULT_SERVICE_CIDR="10.233.0.0/18"

declare -a NODE_NAMES=()
declare -a NODE_IPS=()
declare -a NODE_ROLES=()
declare -A SEEN_NODES=()
declare -a MASTER_HOSTS=()
declare -a WORKER_HOSTS=()
SSH_PRIVATE_KEY=
AUTO_APPROVE=false
REQUESTED_CLUSTER_NAME=

usage() {
  cat <<'EOF'
Usage:
  ./kubespray-wizard.sh -m MASTER_LIST -w WORKER_LIST [-k PRIVATE_KEY] [--cluster-name NAME] [-y]
  ./kubespray-wizard.sh --resume CLUSTER_NAME [-k PRIVATE_KEY] [-y]
  ./kubespray-wizard.sh --add-server HOST --cluster-name NAME [--server-ip IP] [-k PRIVATE_KEY] [-y] [--dry-run]

Examples:
  # Standalone node: the same server is master and worker
  ./kubespray-wizard.sh \
    -m worker-01 \
    -w worker-01

  # Three control-plane/etcd nodes that also run workloads
  ./kubespray-wizard.sh \
    -m control-01,control-02,control-03 \
    -w control-01,control-02,control-03

--add-server joins one worker to a saved inventory using scale.yml. It preserves
control-plane/etcd membership and never resets an existing cluster. --server-ip
overrides hostname resolution. --dry-run previews without changes. This action
requires python3-yaml. Use -y to apply without the typed APPLY prompt.

Lists may be comma-separated or quoted and space-separated. The master list
must contain exactly one or three unique servers. A server in both lists is
assigned both roles. --cluster-name NAME sets the inventory and Kubespray cluster
name. The internal cluster DNS domain is set separately to cluster.local.
Use lowercase letters,
digits, and hyphens, starting with a letter or digit. Without this flag, the
inventory name is generated automatically; DNS still uses cluster.local.
The optional
-k flag selects a private key; otherwise the first usable key from `ssh -G` is
selected automatically. (`-k` is a wizard option, not Ansible's password flag.)

The script uses root SSH, the default pod/service CIDRs, and key-only login. It
never accepts or stores passwords. Docker is required only on this control
host. The wizard does not create VM snapshots/backups or require backup confirmation.
An exact typed APPLY approval remains required
unless `-y` explicitly authorizes a non-interactive deployment.
Inventories are saved under ./infra/kubespray/inventories and deployment artifacts
under ./.state/kubespray/artifacts, relative to the directory you run from.
Before install, resume, or worker-add, the wizard writes a dedicated kubelet DNS
file on the target nodes. It uses upstream_dns_servers from the inventory when
set, otherwise existing node resolvers; it excludes loopback and cluster ranges
and keeps at most three unique servers. No usable upstream aborts deployment.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

validate_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
}

validate_cluster_name() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9-]*$ ]]
}

validate_ipv4() {
  python3 - "$1" <<'PY'
import ipaddress
import sys

try:
    address = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if address.version == 4 else 1)
PY
}

validate_cidrs() {
  python3 - "$1" "$2" <<'PY'
import ipaddress
import sys

try:
    pod = ipaddress.ip_network(sys.argv[1], strict=True)
    service = ipaddress.ip_network(sys.argv[2], strict=True)
except ValueError as error:
    print(f"invalid CIDR: {error}", file=sys.stderr)
    raise SystemExit(1)
if pod.version != 4 or service.version != 4:
    print("only IPv4 pod/service CIDRs are supported by this wizard", file=sys.stderr)
    raise SystemExit(1)
if pod.overlaps(service):
    print("pod and service CIDRs overlap", file=sys.stderr)
    raise SystemExit(1)
PY
}

select_private_key() {
  local ssh_target=$1
  local account_home candidate

  account_home=$(getent passwd "$(id -u)" | awk -F: 'NR == 1 {print $6}')
  [ -n "$account_home" ] || die "could not determine the current account home"

  while read -r candidate; do
    candidate=${candidate//%d/$account_home}
    case "$candidate" in
      "~/"*) candidate="$account_home/${candidate#~/}" ;;
    esac
    if [ -f "$candidate" ] && [ -r "$candidate" ]; then
      SSH_PRIVATE_KEY=$candidate
      return 0
    fi
  done < <(ssh -G "$ssh_target" 2>/dev/null |
    awk '$1 == "identityfile" {print $2}')

  die "no usable private key found; pass one with -k PRIVATE_KEY"
}

set_private_key() {
  local requested_key=$1

  if [[ "$requested_key" = /* ]]; then
    SSH_PRIVATE_KEY=$requested_key
  else
    SSH_PRIVATE_KEY="$PWD/$requested_key"
  fi
  [ -f "$SSH_PRIVATE_KEY" ] || {
    die "private key not found: $SSH_PRIVATE_KEY"
  }
  [ -r "$SSH_PRIVATE_KEY" ] || {
    die "private key is not readable: $SSH_PRIVATE_KEY"
  }
}

resolve_dns_ipv4() {
  local server=$1
  local address=

  if command -v nslookup >/dev/null 2>&1; then
    address=$(nslookup "$server" 2>/dev/null |
      awk '/^Address: / && $2 !~ /#/ && $2 ~ /^[0-9.]+$/ {print $2; exit}')
  fi
  if [ -z "$address" ]; then
    address=$(getent ahostsv4 "$server" 2>/dev/null |
      awk '$2 == "STREAM" && $1 ~ /^[0-9.]+$/ {print $1; exit}')
  fi
  printf '%s\n' "$address"
}

verify_node() {
  local ssh_target=$1
  local expected_hostname=$2
  local identity observed_hostname ssh_ip

  identity=$(timeout 12 ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=8 \
    -o IdentitiesOnly=yes \
    -o "IdentityFile=$SSH_PRIVATE_KEY" \
    -o UserKnownHostsFile=/dev/null \
    -o GlobalKnownHostsFile=/dev/null \
    -o StrictHostKeyChecking=no \
    -o UpdateHostKeys=no \
    "$ssh_target" \
    'hostnamectl --static; set -- $SSH_CONNECTION; printf "%s\n" "$3"') || {
    printf 'Key-only SSH failed for %s.\n' "$ssh_target" >&2
      printf 'Verify the key with: ssh -i %q %q\n' \
        "$SSH_PRIVATE_KEY" "$ssh_target" >&2
      return 1
    }

  observed_hostname=$(printf '%s\n' "$identity" | sed -n '1p')
  ssh_ip=$(printf '%s\n' "$identity" | sed -n '2p')
  if [ "$observed_hostname" != "$expected_hostname" ]; then
    printf 'Hostname mismatch: requested=%s observed=%s\n' \
      "$expected_hostname" "$observed_hostname" >&2
    return 1
  fi
  if [ -z "$ssh_ip" ] || ! validate_ipv4 "$ssh_ip"; then
    printf 'Could not determine the SSH destination IPv4 for %s.\n' \
      "$expected_hostname" >&2
    return 1
  fi
  printf '%s\n' "$ssh_ip"
}

add_node() {
  local ssh_user=$1
  local server=$2
  local role=$3
  local dns_ip ssh_ip node_ip ssh_target

  validate_name "$server" || {
    printf 'Use only letters, numbers, dots, underscores, and hyphens.\n' >&2
    return 1
  }
  [ -z "${SEEN_NODES[$server]:-}" ] || {
    printf 'Server already added: %s\n' "$server" >&2
    return 1
  }

  ssh_target="${ssh_user}@${server}"
  ssh_ip=$(verify_node "$ssh_target" "$server") || return 1

  dns_ip=$(resolve_dns_ipv4 "$server" || true)
  if [ -n "$dns_ip" ] && ! validate_ipv4 "$dns_ip"; then
    printf 'Ignoring invalid DNS result for %s: %s\n' "$server" "$dns_ip" >&2
    dns_ip=
  fi
  if [ -n "$dns_ip" ] && [ "$dns_ip" != "$ssh_ip" ]; then
    printf 'Address mismatch for %s: DNS=%s SSH-destination=%s\n' \
      "$server" "$dns_ip" "$ssh_ip" >&2
    printf 'Refusing to guess which address Kubernetes should advertise.\n' >&2
    return 1
  fi
  node_ip=$ssh_ip
  if [ -n "$dns_ip" ]; then
    printf 'Resolved and SSH-verified %s as %s.\n' "$server" "$node_ip"
  else
    printf 'DNS returned no IPv4; using SSH-verified destination %s for %s.\n' \
      "$node_ip" "$server"
  fi

  SEEN_NODES[$server]=1
  NODE_NAMES+=("$server")
  NODE_IPS+=("$node_ip")
  NODE_ROLES+=("$role")
  printf 'Added %s (%s, %s).\n' "$server" "$node_ip" "$role"
}

append_host_list() {
  local raw_list=$1
  local destination_name=$2
  local normalized host
  local -a parsed=()
  local -n destination=$destination_name

  normalized=${raw_list//,/ }
  read -r -a parsed <<<"$normalized"
  [ "${#parsed[@]}" -gt 0 ] || die "empty server list"
  for host in "${parsed[@]}"; do
    validate_name "$host" || die "invalid server name: $host"
    destination+=("$host")
  done
}

build_nodes_from_flags() {
  local ssh_user=$1
  local host role
  local -a ordered_hosts=()
  local -A masters=()
  local -A workers=()
  local -A ordered=()

  for host in "${MASTER_HOSTS[@]}"; do
    masters["$host"]=1
    if [ -z "${ordered[$host]:-}" ]; then
      ordered["$host"]=1
      ordered_hosts+=("$host")
    fi
  done
  [ "${#masters[@]}" -eq "${#MASTER_HOSTS[@]}" ] || {
    die "the master list contains a duplicate server"
  }
  [ "${#masters[@]}" -eq 1 ] || [ "${#masters[@]}" -eq 3 ] || {
    die "the master list must contain exactly one or three unique servers"
  }

  for host in "${WORKER_HOSTS[@]}"; do
    workers["$host"]=1
    if [ -z "${ordered[$host]:-}" ]; then
      ordered["$host"]=1
      ordered_hosts+=("$host")
    fi
  done
  [ "${#workers[@]}" -eq "${#WORKER_HOSTS[@]}" ] || {
    die "the worker list contains a duplicate server"
  }
  [ "${#workers[@]}" -gt 0 ] || die "the worker list must not be empty"

  for host in "${ordered_hosts[@]}"; do
    if [ -n "${masters[$host]:-}" ] && [ -n "${workers[$host]:-}" ]; then
      role=both
    elif [ -n "${masters[$host]:-}" ]; then
      role=master
    else
      role=worker
    fi
    add_node "$ssh_user" "$host" "$role" || die "node verification failed: $host"
  done
}

validate_topology() {
  local index role
  local masters=0
  local workers=0

  [ "${#NODE_NAMES[@]}" -gt 0 ] || die "no servers were entered"
  for index in "${!NODE_NAMES[@]}"; do
    role=${NODE_ROLES[$index]}
    case "$role" in
      master)
        masters=$((masters + 1))
        ;;
      worker)
        workers=$((workers + 1))
        ;;
      both)
        masters=$((masters + 1))
        workers=$((workers + 1))
        ;;
    esac
  done

  [ "$masters" -gt 0 ] || die "at least one master or both-role node is required"
  [ "$workers" -gt 0 ] || die "at least one worker or both-role node is required"

  if [ "$masters" -gt 1 ] && [ $((masters % 2)) -eq 0 ]; then
    printf 'WARNING: %s etcd members is an even count; use an odd count for quorum.\n' \
      "$masters" >&2
    read -r -p 'Continue with an even etcd member count? [y/N]: ' answer
    [[ "$answer" =~ ^[Yy]$ ]] || die "topology rejected"
  fi
}

write_host_entries() {
  local output=$1
  local ssh_user=$2
  local index

  {
    printf 'all:\n'
    printf '  hosts:\n'
    for index in "${!NODE_NAMES[@]}"; do
      printf '    %s:\n' "${NODE_NAMES[$index]}"
      printf '      ansible_host: %s\n' "${NODE_NAMES[$index]}"
      printf '      ansible_user: %s\n' "$ssh_user"
      printf '      ip: %s\n' "${NODE_IPS[$index]}"
      printf '      access_ip: %s\n' "${NODE_IPS[$index]}"
    done
    printf '  children:\n'
    printf '    kube_control_plane:\n'
    printf '      hosts:\n'
    for index in "${!NODE_NAMES[@]}"; do
      case "${NODE_ROLES[$index]}" in
        master|both)
          printf '        %s: {}\n' "${NODE_NAMES[$index]}"
          ;;
      esac
    done
    printf '    etcd:\n'
    printf '      hosts:\n'
    for index in "${!NODE_NAMES[@]}"; do
      case "${NODE_ROLES[$index]}" in
        master|both)
          printf '        %s: {}\n' "${NODE_NAMES[$index]}"
          ;;
      esac
    done
    printf '    kube_node:\n'
    printf '      hosts:\n'
    for index in "${!NODE_NAMES[@]}"; do
      case "${NODE_ROLES[$index]}" in
        worker|both)
          printf '        %s: {}\n' "${NODE_NAMES[$index]}"
          ;;
      esac
    done
    printf '    k8s_cluster:\n'
    printf '      children:\n'
    printf '        kube_control_plane: {}\n'
    printf '        kube_node: {}\n'
    printf '    calico_rr:\n'
    printf '      hosts: {}\n'
  } >"$output"
}

write_inventory() {
  local cluster_name=$1
  local ssh_user=$2
  local pod_cidr=$3
  local service_cidr=$4
  local destination="$INVENTORY_ROOT/$cluster_name"
  local staging
  local index

  [ ! -e "$destination" ] || {
    die "inventory already exists; resume with: $0 --resume $cluster_name"
  }

  staging=$(mktemp -d /tmp/kubespray-wizard.XXXXXXXX)
  trap 'case "${staging:-}" in /tmp/kubespray-wizard.*) rm -rf -- "$staging";; esac' EXIT

  mkdir -p \
    "$staging/group_vars/all" \
    "$staging/group_vars/k8s_cluster"

  write_host_entries "$staging/hosts.yml" "$ssh_user"

  {
    printf '%s\n' '---'
    printf '%s\n' 'ansible_become: true'
    printf '%s\n' 'ansible_become_user: root'
    printf '%s\n' 'ansible_ssh_private_key_file: /root/.ssh/kubespray_key'
    printf "%s\n" \
      "ansible_ssh_common_args: '-o UserKnownHostsFile=/dev/null -o GlobalKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o UpdateHostKeys=no'"
  } >"$staging/group_vars/all/all.yml"

  {
    printf '%s\n' '---'
    printf 'kube_version: %s\n' "$KUBE_VERSION"
    if [ -n "$REQUESTED_CLUSTER_NAME" ]; then
      printf "cluster_name: '%s'\n" "$cluster_name"
    fi
    printf '%s\n' 'dns_domain: cluster.local'
    printf '%s\n' 'container_manager: containerd'
    printf '%s\n' 'kube_network_plugin: calico'
    printf '%s\n' 'kube_proxy_mode: ipvs'
    printf '%s\n' 'kube_proxy_strict_arp: true'
    printf 'kube_pods_subnet: %s\n' "$pod_cidr"
    printf 'kube_service_addresses: %s\n' "$service_cidr"
    printf '%s\n' 'enable_nodelocaldns: false'
    printf '%s\n' 'kubeconfig_localhost: true'
    printf '%s\n' 'kubeconfig_localhost_ansible_host: true'
    printf '%s\n' 'kubectl_localhost: true'
    printf '%s\n' 'artifacts_dir: /artifacts'
  } >"$staging/group_vars/k8s_cluster/k8s-cluster.yml"

  {
    printf '%s\n' '---'
    printf '%s\n' 'local_path_provisioner_enabled: true'
    printf '%s\n' 'local_path_provisioner_namespace: local-path-storage'
    printf '%s\n' 'local_path_provisioner_storage_class: local-path'
    printf '%s\n' 'local_path_provisioner_claim_root: /opt/local-path-provisioner/'
    printf '%s\n' 'local_path_provisioner_is_default_storageclass: "true"'
    printf '%s\n' 'local_path_provisioner_reclaim_policy: Retain'
  } >"$staging/group_vars/k8s_cluster/addons.yml"

  {
    printf '# Kubespray Inventory: %s\n\n' "$cluster_name"
    printf 'Generated by `./kubespray-wizard.sh`.\n\n'
    printf -- '- Kubespray: `%s` (`%s`)\n' "$KUBESPRAY_TAG" "$KUBESPRAY_COMMIT"
    printf -- '- Kubernetes: `%s`\n' "$KUBE_VERSION"
    printf -- '- containerd default from pinned Kubespray: `%s`\n' "$CONTAINERD_VERSION"
    printf -- '- Calico default from pinned Kubespray: `%s`\n' "$CALICO_VERSION"
    printf -- '- Pod CIDR: `%s`\n' "$pod_cidr"
    printf -- '- Service CIDR: `%s`\n\n' "$service_cidr"
    printf 'No passwords, private keys, kubeconfigs, or registry tokens belong in this directory.\n\n'
    printf 'This wizard does not create VM snapshots or backups.\n'
    printf 'Kubernetes downgrade is not a supported rollback strategy.\n'
  } >"$staging/README.md"

  {
    printf 'cluster=%s\n' "$cluster_name"
    printf 'kubespray_tag=%s\n' "$KUBESPRAY_TAG"
    printf 'kubespray_commit=%s\n' "$KUBESPRAY_COMMIT"
    printf 'kubernetes=%s\n' "$KUBE_VERSION"
    printf 'containerd=%s\n' "$CONTAINERD_VERSION"
    printf 'calico=%s\n' "$CALICO_VERSION"
    for index in "${!NODE_NAMES[@]}"; do
      printf 'node=%s ip=%s role=%s\n' \
        "${NODE_NAMES[$index]}" "${NODE_IPS[$index]}" "${NODE_ROLES[$index]}"
    done
  } >"$staging/manifest.txt"

  mkdir -p "$INVENTORY_ROOT"
  mv -- "$staging" "$destination"
  trap - EXIT
  printf 'Inventory created: %s\n' "$destination"
}

prepare_kubespray_image() {
  local pull_answer image_id image_digest

  require_command docker
  docker info >/dev/null 2>&1 || {
    die "Docker is installed but its daemon is unavailable to this user"
  }

  if ! docker image inspect "$KUBESPRAY_IMAGE" >/dev/null 2>&1; then
    printf 'The official Kubespray image is not present locally:\n  %s\n' \
      "$KUBESPRAY_IMAGE"
    if ! $AUTO_APPROVE; then
      read -r -p 'Pull this image from Quay now? [y/N]: ' pull_answer
      [[ "$pull_answer" =~ ^[Yy]$ ]] || die "image pull cancelled"
    fi
    docker pull "$KUBESPRAY_IMAGE"
  fi

  image_id=$(docker image inspect \
    --format '{{.Id}}' "$KUBESPRAY_IMAGE")
  image_digest=$(docker image inspect \
    --format '{{json .RepoDigests}}' "$KUBESPRAY_IMAGE")
  printf 'Using Kubespray image ID: %s\n' "$image_id"
  if [ -n "$image_digest" ]; then
    printf 'Verified local repository digest: %s\n' "$image_digest"
  fi
}

run_kubespray_container() {
  local inventory_dir=$1
  shift
  local cluster_name artifact_dir

  [ -f "$SSH_PRIVATE_KEY" ] || die "SSH private key is not available"
  cluster_name=${inventory_dir##*/}
  artifact_dir="$PROJECT_ROOT/.state/kubespray/artifacts/$cluster_name"
  mkdir -p "$artifact_dir"
  chmod 700 "$PROJECT_ROOT/.state" \
    "$PROJECT_ROOT/.state/kubespray" \
    "$PROJECT_ROOT/.state/kubespray/artifacts" \
    "$artifact_dir"

  docker run --rm --network host \
    --env ANSIBLE_CACHE_PLUGIN_CONNECTION=/artifacts/ansible-facts \
    --mount "type=bind,source=$inventory_dir,destination=/inventory,readonly" \
    --mount "type=bind,source=$SSH_PRIVATE_KEY,destination=/root/.ssh/kubespray_key,readonly" \
    --mount "type=bind,source=$artifact_dir,destination=/artifacts" \
    "$KUBESPRAY_IMAGE" \
    "$@"
}

show_plan() {
  local cluster_name=$1
  local index

  printf '\nDeployment plan\n'
  printf 'Cluster: %s\n' "$cluster_name"
  printf 'Kubespray: %s (%s)\n' "$KUBESPRAY_TAG" "$KUBESPRAY_COMMIT"
  printf 'Kubernetes: %s\n' "$KUBE_VERSION"
  printf '%-32s %-15s %-8s\n' 'SERVER' 'IP' 'ROLE'
  for index in "${!NODE_NAMES[@]}"; do
    printf '%-32s %-15s %-8s\n' \
      "${NODE_NAMES[$index]}" "${NODE_IPS[$index]}" "${NODE_ROLES[$index]}"
  done
}

write_dns_playbook() {
  cat > "$1" <<'DNS'
- name: Prepare upstream-only kubelet DNS
  hosts: k8s_cluster
  gather_facts: false
  serial: 1
  any_errors_fatal: true
  tasks:
    - name: Locate systemd upstream resolver file
      ansible.builtin.stat:
        path: /run/systemd/resolve/resolv.conf
      register: upstream_resolv
    - name: Select usable upstream DNS without cluster forwarding loops
      ansible.builtin.command:
        argv:
          - python3
          - -c
          - |
            import ipaddress, json, pathlib, sys
            configured = json.loads(sys.argv[1])
            networks = [ipaddress.ip_network(n.strip()) for n in sys.argv[2].split(',') if n.strip()]
            domain = sys.argv[3].rstrip('.')
            lines = pathlib.Path(sys.argv[4]).read_text().splitlines()
            discovered, searches = [], []
            for line in lines:
                fields = line.split('#', 1)[0].split()
                if len(fields) > 1 and fields[0] == 'nameserver':
                    discovered.append(fields[1])
                if len(fields) > 1 and fields[0] == 'search':
                    searches = [s for s in fields[1:] if s.rstrip('.') != domain
                                and not s.rstrip('.').endswith('.' + domain)]
            if not isinstance(configured, list):
                sys.exit('upstream_dns_servers must be a list of IP addresses')
            servers = []
            for value in configured or discovered:
                address = ipaddress.ip_address(value)
                if (address.is_loopback or address.is_link_local or address.is_unspecified
                        or address.is_multicast or any(address in n for n in networks)):
                    continue
                value = str(address)
                if value not in servers:
                    servers.append(value)
            if not servers:
                sys.exit('No usable upstream DNS; set upstream_dns_servers in the inventory')
            for server in servers[:3]:
                print('nameserver ' + server)
            if searches:
                print('search ' + ' '.join(dict.fromkeys(searches)))
          - '{{ upstream_dns_servers | default([]) | to_json }}'
          - '{{ kube_service_subnets | default(kube_service_addresses | default("10.233.0.0/18")) }},{{ kube_pods_subnet | default("10.233.64.0/18") }}'
          - '{{ dns_domain | default(cluster_name | default("cluster.local")) }}'
          - '{{ "/run/systemd/resolve/resolv.conf" if upstream_resolv.stat.exists else "/etc/resolv.conf" }}'
      register: kubelet_upstreams
      changed_when: false
    - name: Ensure kubelet configuration directory exists
      ansible.builtin.file:
        path: /etc/kubernetes
        state: directory
        mode: '0755'
    - name: Write persistent upstream-only resolver file
      ansible.builtin.copy:
        dest: /etc/kubernetes/kubelet-resolv.conf
        content: |
          {{ kubelet_upstreams.stdout }}
        owner: root
        group: root
        mode: '0644'
        backup: true
DNS
}

prepare_cluster_dns() {
  local cluster=$1 limit=${2:-k8s_cluster}
  local artifact_dir="$PROJECT_ROOT/.state/kubespray/artifacts/$cluster"
  mkdir -p "$artifact_dir"
  write_dns_playbook "$artifact_dir/prepare-dns.yml"
  # Extra vars override Kubespray's Ubuntu-specific include_vars defaults.
  printf '%s\n' 'kube_resolv_conf: /etc/kubernetes/kubelet-resolv.conf' \
    > "$INVENTORY_ROOT/$cluster/dns-extra-vars.yml"
  run_kubespray_container "$INVENTORY_ROOT/$cluster" ansible-playbook \
    -i /inventory/hosts.yml -b /artifacts/prepare-dns.yml --limit "$limit"
}

run_preflight_and_apply() {
  local cluster_name=$1
  local inventory="$INVENTORY_ROOT/$cluster_name/hosts.yml"
  local confirmation

  prepare_kubespray_image

  printf '\nRunning key-only Ansible connectivity preflight...\n'
  run_kubespray_container \
    "$INVENTORY_ROOT/$cluster_name" \
    ansible \
    all \
    --inventory /inventory/hosts.yml \
    --module-name ping

  printf '\nPreflight passed. cluster.yml will install/modify Kubernetes,\n'
  printf 'containerd, networking, firewall/sysctl state, and services on every listed node.\n'
  printf 'Abort conditions include CIDR collision, unsupported cgroup mode,\n'
  printf 'DNS/NTP/registry failure, insufficient resources, or failed connectivity.\n\n'

  if [ "$AUTO_APPROVE" = true ]; then
    printf 'Non-interactive -y approval supplied; proceeding without prompts.\n'
  else
    read -r -p "Type 'APPLY' to run Kubespray on cluster $cluster_name: " confirmation
    [ "$confirmation" = "APPLY" ] || die "apply cancelled"
  fi

  prepare_cluster_dns "$cluster_name"
  run_kubespray_container \
    "$INVENTORY_ROOT/$cluster_name" \
    ansible-playbook \
    --inventory /inventory/hosts.yml \
    --become \
    --extra-vars @/inventory/dns-extra-vars.yml \
    cluster.yml

  printf '\nKubespray completed. Validate nodes, system pods, DNS, pod/service\n'
  printf 'connectivity, NetworkPolicy, reboot persistence, and resource pressure.\n'
}

resume_inventory() {
  local cluster_name=$1
  local inventory_dir="$INVENTORY_ROOT/$cluster_name"

  validate_cluster_name "$cluster_name" || die "invalid cluster name"
  [ -f "$inventory_dir/hosts.yml" ] || {
    die "saved inventory not found: $inventory_dir/hosts.yml"
  }
  [ -f "$inventory_dir/manifest.txt" ] || {
    die "saved inventory manifest not found: $inventory_dir/manifest.txt"
  }

  printf 'Resuming saved inventory:\n'
  sed -n '1,80p' "$inventory_dir/manifest.txt"
  run_preflight_and_apply "$cluster_name"
}

# Add one worker to an existing inventory; reset is always a separate operation.
worker_inventory() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import ipaddress, os, sys, tempfile
try:
    import yaml
except ImportError:
    sys.exit('ERROR: Install python3-yaml to use --add-server.')
path, name, address, action = sys.argv[1:]
data = yaml.safe_load(open(path))
root = data['all']; hosts = root['hosts']; groups = root['children']
for group in ('kube_control_plane', 'etcd'):
    if name in groups.get(group, {}).get('hosts', {}):
        sys.exit('ERROR: Refusing to add an existing control-plane/etcd server as a worker.')
masters = groups.get('kube_control_plane', {}).get('hosts', {})
if not masters:
    sys.exit('ERROR: Saved inventory has no control-plane servers.')
if address:
    ipaddress.IPv4Address(address)
else:
    address = hosts.get(name, {}).get('ip', '')
if not address:
    sys.exit('ERROR: Cannot resolve server address; provide --server-ip IPv4.')
for other, details in hosts.items():
    if other != name and address in (details.get('ip'), details.get('access_ip'), details.get('ansible_host')):
        sys.exit('ERROR: Server address is already assigned to another inventory host.')
if name in hosts and hosts[name].get('ip') != address:
    sys.exit('ERROR: Existing worker address differs; refusing to overwrite it.')
hosts.setdefault(name, {'ansible_host': address, 'ansible_user': 'root', 'ip': address, 'access_ip': address})
groups.setdefault('kube_node', {}).setdefault('hosts', {})[name] = {}
if action == 'write':
    fd, temporary = tempfile.mkstemp(prefix='.hosts-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as handle:
            yaml.safe_dump(data, handle, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
else:
    print(yaml.safe_dump(data, sort_keys=False), end='')
PY
}

add_server_main() {
  local server= cluster= address= dry_run=false inventory confirmation master ca node_state
  while (( $# )); do
    case $1 in
      --add-server|--cluster-name|--server-ip|-k)
        (( $# >= 2 )) && [[ -n $2 && $2 != -* ]] || die "$1 requires a value"
        case $1 in
          --add-server) [[ -z $server ]] || die 'Choose one server'; server=$2 ;;
          --cluster-name) cluster=$2 ;;
          --server-ip) address=$2 ;;
          -k) set_private_key "$2" ;;
        esac
        shift 2 ;;
      --dry-run) dry_run=true; shift ;;
      -y) AUTO_APPROVE=true; shift ;;
      --help|-h) usage; return ;;
      *) die "Unknown --add-server argument: $1" ;;
    esac
  done
  validate_name "$server" || die 'Invalid server name'
  [[ "$server" == "${server,,}" ]] || die 'Use a lowercase server hostname'
  validate_cluster_name "$cluster" || die '--add-server requires --cluster-name of an existing cluster'
  require_command python3
  inventory="$INVENTORY_ROOT/$cluster/hosts.yml"
  [[ -f $inventory ]] || die "Saved inventory not found: $inventory"
  [[ -n $address ]] || address=$(resolve_dns_ipv4 "$server" || true)
  if [[ -z $address ]]; then
    address=$(python3 - "$inventory" "$server" <<'ADDRESS'
import sys
try:
    import yaml
except ImportError:
    sys.exit('ERROR: Install python3-yaml to use --add-server.')
x=yaml.safe_load(open(sys.argv[1]))
print(x['all']['hosts'].get(sys.argv[2], {}).get('ip', ''))
ADDRESS
)
  fi
  # Validate and show the proposed inventory before any writes or host changes.
  worker_inventory "$inventory" "$server" "$address" preview
  printf '\nWorker-only command: ansible-playbook -i /inventory/hosts.yml -b scale.yml --limit %s\n' "$server"
  if $dry_run; then printf 'Preview complete; no inventory or server changes.\n'; return; fi
  require_command ssh; require_command timeout; require_command docker; require_command flock
  [[ -n $SSH_PRIVATE_KEY ]] || select_private_key "root@$address"
  local ssh_options=(-o BatchMode=yes -o ConnectTimeout=8 -o IdentitiesOnly=yes -i "$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
  [[ $(verify_node "root@$address" "$server") == "$address" ]] || die 'SSH host identity/address mismatch'
  node_state=$(timeout 15 ssh "${ssh_options[@]}" "root@$address" '
    if [ -f /etc/kubernetes/manifests/kube-apiserver.yaml ]; then echo control-plane;
    elif [ -f /etc/kubernetes/kubelet.conf ]; then
      for ca in /etc/kubernetes/ssl/ca.crt /etc/kubernetes/pki/ca.crt; do
        if [ -f "$ca" ]; then openssl x509 -in "$ca" -noout -fingerprint -sha256; exit; fi
      done
      echo unknown-cluster;
    else echo clean; fi')
  [[ $node_state != control-plane ]] || die 'Server belongs to another control-plane. Clean that installation separately first; --add-server never resets it.'
  [[ $node_state != unknown-cluster ]] || die 'Server already belongs to an unidentified cluster. Clean it separately first.'
  if [[ $node_state != clean ]]; then
    master=$(python3 - "$inventory" <<'PY'
import sys,yaml
x=yaml.safe_load(open(sys.argv[1]))['all']
n=next(iter(x['children']['kube_control_plane']['hosts']))
print(x['hosts'][n].get('ansible_host', n))
PY
)
    ca=$(timeout 15 ssh "${ssh_options[@]}" "root@$master" 'for ca in /etc/kubernetes/ssl/ca.crt /etc/kubernetes/pki/ca.crt; do if [ -f "$ca" ]; then openssl x509 -in "$ca" -noout -fingerprint -sha256; exit; fi; done')
    [[ -n $ca && $node_state == "$ca" ]] || die 'Server already belongs to a different or unidentified cluster. Clean it separately first.'
  fi
  if ! $AUTO_APPROVE; then
    read -r -p "Type 'APPLY' to add worker $server to $cluster: " confirmation
    [[ $confirmation == APPLY ]] || die 'Worker addition cancelled'
  fi
  mkdir -p "$PROJECT_ROOT/.state/kubespray"
  exec 9>"$PROJECT_ROOT/.state/kubespray/$cluster.lock"
  flock -n 9 || die 'Another worker addition is running for this cluster'
  prepare_kubespray_image
  worker_inventory "$inventory" "$server" "$address" write
  # Facts from the existing control plane are needed by the limited scale play.
  mkdir -p "$PROJECT_ROOT/.state/kubespray/artifacts/$cluster"
  cat > "$PROJECT_ROOT/.state/kubespray/artifacts/$cluster/worker-facts.yml" <<'FACTS'
- import_playbook: /kubespray/playbooks/boilerplate.yml
- name: Gather network facts before worker scaling
  hosts: all
  gather_facts: true
  roles:
    - kubespray_defaults
    - network_facts
FACTS
  run_kubespray_container "$INVENTORY_ROOT/$cluster" ansible-playbook -i /inventory/hosts.yml -b /artifacts/worker-facts.yml > "$PROJECT_ROOT/.state/kubespray/$cluster-worker-facts.log"
  prepare_cluster_dns "$cluster" "$server"
  set -o pipefail
  run_kubespray_container "$INVENTORY_ROOT/$cluster" ansible-playbook -i /inventory/hosts.yml -b scale.yml --limit "$server" --extra-vars @/inventory/dns-extra-vars.yml 2>&1 | tee "$PROJECT_ROOT/.state/kubespray/$cluster-add-$server.log"
  local client artifact_dir="$PROJECT_ROOT/.state/kubespray/artifacts/$cluster"
  client=$(command -v kubectl || true)
  if [[ -z $client && -r $artifact_dir/kubectl ]]; then
    mkdir -p "$PROJECT_ROOT/.state/kubespray/bin"
    install -m 755 "$artifact_dir/kubectl" "$PROJECT_ROOT/.state/kubespray/bin/kubectl"
    client="$PROJECT_ROOT/.state/kubespray/bin/kubectl"
  fi
  [[ -n $client && -r $artifact_dir/admin.conf ]] || die 'Scaling completed; saved kubeconfig/client missing, so node readiness could not be verified.'
  "$client" --kubeconfig "$artifact_dir/admin.conf" wait --for=condition=Ready "node/$server" --timeout=180s
  "$client" --kubeconfig "$artifact_dir/admin.conf" get node "$server" -o wide
  printf '\nWorker %s is Ready in %s.\n' "$server" "$cluster"
}

main() {
  local cluster_name ssh_user pod_cidr service_cidr master_argument worker_argument
  local requested_key=
  local first_master

  local argument
  for argument in "$@"; do
    if [[ $argument == --add-server ]]; then add_server_main "$@"; return; fi
  done

  if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
  fi
  if [ "${1:-}" = "--resume" ]; then
    [ "$#" -ge 2 ] || {
      usage >&2
      exit 2
    }
    cluster_name=$2
    shift 2
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -k)
          [ "$#" -ge 2 ] || die "-k requires a private key path"
          set_private_key "$2"
          shift 2
          ;;
        -y)
          AUTO_APPROVE=true
          shift
          ;;
        *)
          die "unknown resume argument: $1"
          ;;
      esac
    done
    if [ -z "$SSH_PRIVATE_KEY" ]; then
      select_private_key root@localhost
    fi
    require_command ssh
    require_command timeout
    resume_inventory "$cluster_name"
    exit 0
  fi

  require_command python3
  require_command ssh
  require_command timeout

  while [ "$#" -gt 0 ]; do
    case "$1" in
      -m)
        [ "$#" -ge 2 ] || die "-m requires a master server list"
        master_argument=$2
        append_host_list "$master_argument" MASTER_HOSTS
        shift 2
        ;;
      -w)
        [ "$#" -ge 2 ] || die "-w requires a worker server list"
        worker_argument=$2
        append_host_list "$worker_argument" WORKER_HOSTS
        shift 2
        ;;
      -k)
        [ "$#" -ge 2 ] || die "-k requires a private key path"
        requested_key=$2
        shift 2
        ;;
      -y)
        AUTO_APPROVE=true
        shift
        ;;
      --cluster-name)
        [ "$#" -ge 2 ] && [ -n "$2" ] && [[ "$2" != --* ]] || die "--cluster-name requires a name"
        validate_cluster_name "$2" || die "invalid --cluster-name; use lowercase letters, digits, and hyphens, starting with a letter or digit"
        REQUESTED_CLUSTER_NAME=$2
        shift 2
        ;;
      *)
        usage >&2
        die "unknown argument: $1"
        ;;
    esac
  done

  [ "${#MASTER_HOSTS[@]}" -gt 0 ] || die "-m is required"
  [ "${#WORKER_HOSTS[@]}" -gt 0 ] || die "-w is required"

  ssh_user=root
  if [ -n "$requested_key" ]; then
    set_private_key "$requested_key"
  else
    select_private_key "${ssh_user}@${MASTER_HOSTS[0]}"
  fi
  printf 'Using SSH private key: %s\n' "$SSH_PRIVATE_KEY"
  printf 'WARNING: lab mode disables SSH host-key verification.\n'
  pod_cidr=$DEFAULT_POD_CIDR
  service_cidr=$DEFAULT_SERVICE_CIDR
  validate_cidrs "$pod_cidr" "$service_cidr" || die "invalid network plan"

  build_nodes_from_flags "$ssh_user"
  if [ -n "$REQUESTED_CLUSTER_NAME" ]; then
    cluster_name=$REQUESTED_CLUSTER_NAME
  elif [ "${#MASTER_HOSTS[@]}" -eq 1 ]; then
    first_master=${MASTER_HOSTS[0],,}
    first_master=${first_master//./-}
    first_master=${first_master//_/-}
    cluster_name="nico-${first_master}"
  else
    cluster_name=nico-ha
  fi
  validate_cluster_name "$cluster_name" || die "generated an invalid cluster name"

  validate_topology
  show_plan "$cluster_name"
  write_inventory "$cluster_name" "$ssh_user" "$pod_cidr" "$service_cidr"
  run_preflight_and_apply "$cluster_name"
}

main "$@"

