# DPF-only student installation

1. [Read the PDF](DPF-only-installation.pdf) or [copy commands from the text guide](DPF-only-installation.txt).
2. [Download the lab files](DPF-only-lab-files.zip).
3. Follow the numbered steps: external Argo, prerequisites/DPF, tenants, BMC credentials, HBN, DPU provisioning, Ubuntu SSH and traffic checks.

The lab demonstrates Asia `10.0.0.1/24` and Europe `10.0.0.2/24` in separate HBN networks.
It requires existing Kubernetes, DHCP, Ubuntu hosts and tenant egress routing/NAT.
It does not install NICo or the host operating systems. Provisioning may reimage DPUs;
maintenance holds and external reboot handling are explained in the guide.

| Edit | Purpose |
| --- | --- |
| `config.yaml` | Kubernetes API, tenant VIPs and interface; DHCP disabled in this example |
| `30-hbn-application.yaml` | HBN hostname selectors, VRFs, ASNs, VNIs and pools |
| `40-provisioning-application.yaml` | BMC IPs, device identities, selectors, BFB and DPU flavors |
| `access-pod.yaml` | Management node used for SSH connectivity |
| Private file outside Git | BMC username/password; created in Step 5 |

Files in `lab-files/` contain lab IPs and hardware identities. Change them for another
site. No passwords, private keys, kubeconfigs or real MAC addresses are included.
The Argo sources are pinned to `96b35f74e5df5cc05c864dbb7034cb206f828e2f`.
The HBN/provisioning patches match the lab Application sources captured on 2026-10-19;
patches are formatted as readable YAML rather than embedded JSON.

Validation: configuration Helm render, both Kustomize renders, shell syntax, private-data
checks and visual PDF review. No fresh hardware reinstall was performed for this
handout. The dated runtime observation is on the PDF's final page.

Rebuild PDF/TXT/ZIP with ReportLab and DejaVu fonts installed:

```bash
python3 DPF/user-documentation/dpf-only/build-guide.py
```
