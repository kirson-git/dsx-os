# Validation and provenance

## Reproduce validation

Requirements: Python 3.11+, PyYAML, Helm 3, Git and outbound chart-repository
access.
No command below contacts Kubernetes or modifies hardware.

```bash
git clone https://github.com/dsx-ai-factory/infra-controller.git /tmp/nico-source
git -C /tmp/nico-source checkout 80d131a5cd3280f9cef3131fa0c5647bdf3e79d0
python3 -m unittest discover -s NICo/tests -v
python3 NICo/scripts/validate.py --upstream /tmp/nico-source --fetch-charts
bash NICo/deploy.sh --config NICo/config.yaml --stage 6 --render-only \
  > /tmp/nico-application.yaml
```

Without `--fetch-charts`, validation skips remote charts and reports each
skip.
It renders the pinned local upstream Core chart, local adapters and stage
graph.
The full run fetches the pinned public charts, checks resource ownership,
rejects embedded private Secret values and checks PXE init-container mount
paths.
The DPF operator render uses the vendored v26.4.0 chart also used by
standalone DPF.

Tests cover additive stages, storage opt-in, Argo CRD ownership, TOML parsing,
invalid/overlapping VIPs, unknown config keys, deterministic prerequisite
rendering,
secret handling and private file permissions.
They are not cluster integration tests.

## Source ownership

| Files | Source |
| --- | --- |
| `charts/stack`, `charts/dpf-site`, scripts/tests | This repository's NICo integration |
| `charts/prerequisites` | Pinned NICo `helm-prereqs` chart, Apache-2.0; included LICENSE |
| `manifests/vault-tls` | Rendered bootstrap subset of that pinned prerequisite chart |
| `values/*.yaml` | Pinned NICo operator values, with the overrides described below |
| `charts/kamaji` | Kamaji 1.2.0 rendered from `DPF/charts/kamaji-1.2.0.tgz`, using existing DPF Argo adapter logic |
| `charts/storage` | Rancher local-path-provisioner 0.0.34 chart from the lab prerequisite source |
| Core chart and monitoring CRDs | Fetched from the pinned upstream NICo commit at sync time |

Upstream NICo source:
<https://github.com/dsx-ai-factory/infra-controller/tree/80d131a5cd3280f9cef3131fa0c5647bdf3e79d0>.

Intentional prerequisite adaptations: remove transient Helm hook ownership
from
persistent objects; run Vault PKI as an Argo Sync hook before its
ClusterIssuer;
create private keys/tokens separately; disable factory-password seeding, REST,
Flow and RMS; verify Vault/Kubernetes TLS; scope PostgreSQL Secret access to
its
namespace. The job's shell-capable kubectl image is pinned separately.

Kamaji keeps the existing DPF datastore-bootstrap ordering, CA retry guards
and
portable shell adaptation. Service Argo disables shared CRD installation and
uses
a distinct installation ID. The external Argo values provide CRD health
handling.
Storage remains opt-in; its class name comes from the single config file.

## Qualification boundary

The package is prepared for a clean-cluster lab run. Rendering does not
validate
admission webhooks, actual image startup, resource capacity, Vault Raft
behavior,
BMC credentials, DHCP relay, hardware ingestion or DPU/host network isolation.
Those are required acceptance tests before production use. The running
standalone
Europe/Asia environment was not migrated as part of creating this package.

## Recorded checks — 2026-10-18

- Ten unit tests passed.
- Full pinned-chart validation rendered 405 resources without duplicate owners
  or embedded private Secret values.
- Prerequisite rendering is deterministic; Core site TOML parses successfully.
- All helper `--help` commands and the render-only workflow were exercised.
- Markdown lint and whitespace checks passed.
- Review fixes cover PXE mount paths, Vault TLS verification, namespace-scoped
  ESO Secret access, and a shell-capable bootstrap image.
- `alpine/k8s:1.34.1` is pinned by multiarchitecture manifest digest; amd64
  layers contain executable kubectl, sh and cat. No image runtime test was run.
- No live cluster installation or hardware ingestion was performed.

Vendored source archive SHA-256 values:

```text
43ab7711f8ea49dd3a9b3b587585dd1769b5cc5591232d91f940b4a02be3322a  DPF/charts/kamaji-1.2.0.tgz
0f9a18a0d64958e2f1769bdb468a46ad65e0ea485dadb86cad9e6457b3cec69a  DPF/charts/dpf-operator-v26.4.0.tgz
```
