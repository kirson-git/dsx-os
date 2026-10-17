# Install DPF + HBN with Argo CD

Six steps for the **prepared Europe/Asia lab on nico-lab**.
Requires working management Kubernetes, Git, kubectl, Helm, Python 3 and PyYAML.
Existing host Ubuntu, DHCP and switch/router settings stay in place.

```text
Management Kubernetes -> DPF -> Europe DPU + Asia DPU
                            -> HBN + Zero Trust provisioning
```

## Step 1 — Get the installer

Run in Bash on the administration server:

```bash
test -d /tmp/dsx-os-dpf/.git || \
  git clone https://github.com/kirson-git/dsx-os.git /tmp/dsx-os-dpf
cd /tmp/dsx-os-dpf
git pull --ff-only
kubectl get nodes
command -v helm kubectl python3
python3 -c 'import yaml'
```

Expected: management nodes `Ready`; tools available.

## Step 2 — Edit your IP settings

Your prepared file is local, outside Git. For another site,
[prepare its Application first](TWO-COMMAND-INSTALL.md#prepare-a-sites-application-once).

```bash
vi /tmp/dpf-lab/install.yaml
```

| Setting | Europe | Asia |
| --- | --- | --- |
| Tenant API VIP | `192.168.0.200` | `192.168.0.203` |
| DPU BMC | `192.168.0.246` | `192.168.0.249` |
| Server iDRAC | `192.168.0.241` | `192.168.0.243` |
| DPU OS, existing DHCP | `192.168.0.244` | `192.168.0.242` |
| Ubuntu data IP, retained | `10.0.0.2/24` | `10.0.0.1/24` |

Management API: `10.220.175.20`. Keep `install-dhcp: "no"`: existing DHCP
supplies the DPU OS addresses. Tenant VIPs are manual reservations.
BMC address changes must also update matching labels/selectors in this file.

## Step 3 — Enter passwords and check access

Both management usernames are `root` in this BF3 lab. Passwords stay outside Git.
**If the two files already contain your passwords, skip the input lines.**

```bash
install -d -m 700 /tmp/dpf-lab/private
umask 077
read -r -s -p 'DPU BMC password: ' dpf_password; printf '\n'
printf '%s' "$dpf_password" > /tmp/dpf-lab/private/bmc-password; unset dpf_password
read -r -s -p 'Server iDRAC password: ' dpf_password; printf '\n'
printf '%s' "$dpf_password" > /tmp/dpf-lab/private/idrac-password; unset dpf_password
chmod 600 /tmp/dpf-lab/private/bmc-password /tmp/dpf-lab/private/idrac-password

bash DPF/bootstrap-credentials.sh --config /tmp/dpf-lab/install.yaml \
  --bmc-password-file /tmp/dpf-lab/private/bmc-password \
  --idrac-password-file /tmp/dpf-lab/private/idrac-password \
  --insecure-bmc --check-only
```

Expected: **four PASS results** from a temporary Kubernetes pod.
This checks BMC/iDRAC credentials and serials, not SSH or DHCP.
`--insecure-bmc` accepts our self-signed lab certificates; omit it for trusted
certificates. iDRAC TLS checking follows `bootstrap.hosts[].verifyTLS`.

## Step 4 — Install external Argo CD

**Replacing the old staged Applications?** Complete cleanup first, or keep the
working demo. Do not combine `dpf-platform`, `dpf-site`, `dpf-hbn` and
`dpf-provisioning` with the new `dpf` app. Skip cleanup on a fresh cluster.

**Optional clean reset — destructive:**

Removes DPF/HBN, tenants and their storage, dedicated prerequisites, external
Argo and their CRDs. Keeps management Kubernetes, host Ubuntu and external networking.

```bash
bash DPF/install.sh --action delete-plan
bash DPF/install.sh --action delete
```

Type the exact cluster context. Stop on errors.

Install/upgrade external Argo using Helm; the script prints its commands:

```bash
bash DPF/install.sh --action argo
```

Expected: the Helm command succeeds and Argo workloads are ready.

## Step 5 — Save Secrets and apply ONE YAML

This can reimage DPUs and restart their attached hosts.

```bash
bash DPF/bootstrap-credentials.sh --config /tmp/dpf-lab/install.yaml \
  --bmc-password-file /tmp/dpf-lab/private/bmc-password \
  --idrac-password-file /tmp/dpf-lab/private/idrac-password \
  --insecure-bmc && \
kubectl apply -f /tmp/dpf-lab/install.yaml && \
kubectl -n argocd get application dpf -w
```

Argo installs **storage, cert-manager, Kamaji, NFD, maintenance operator, DPF,
Europe/Asia tenants, HBN and DPU provisioning**. No extra stage YAMLs are needed.
Ctrl+C stops watching; installation continues.

## Step 6 — Verify installation

```bash
kubectl -n argocd get application dpf -o jsonpath='{.status.operationState.phase}{"\n"}'
kubectl get dpuclusters -A
kubectl -n dpf-operator-system get dpus
kubectl -n dpf-operator-system get job dpf-bootstrap-ready
```

Expected: sync `Succeeded`, both tenants/DPUs `Ready`, readiness Job completed.
The Job appears at the final stage and checks DPU, tenant and HBN readiness.
Use the [demo commands](DEMO.txt) to test Ubuntu Internet access and isolation.
A complete clean rebuild still needs end-to-end testing.

If a sync fails, inspect its message before retrying:

```bash
kubectl -n argocd get application dpf -o jsonpath='{.status.operationState.message}{"\n"}'
```

[Passwords](PASSWORDS.md) · [Bash menu](INSTALLER.md) ·
[DHCP](DHCP.md) · [Platform/tenant alternative](PLATFORM-AND-TENANTS.md) ·
[Separate YAML stages](STAGED-INSTALL.md) · [Production settings](PRODUCTION.md)
