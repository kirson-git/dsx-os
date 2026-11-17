# Customer installer rules

- Keep changes small and preserve the working workflow. Do not turn a settings
  or README edit into a new chart, framework, or installer redesign.
- Name the exact file to edit and give complete copy-paste commands. Prefer one
  customer-facing site YAML; mark editable values `# please change here`.
- Prefill verified lab values when requested. Explain DHCP versus manual IPs,
  where DHCP runs, and whether this package installs it. Never guess addresses.
- Describe actual scope: `DPF/config.yaml` configures the operator and tenants
  after platform installation; optional DHCP uses the same file. HBN and
  provisioning remain separate stages.
- Keep the README short: numbered steps and a simple diagram; link longer guides.
- Default to the existing step-by-step workflow with `DPF/config.yaml` as the
  settings file. Do not redirect users to the combined `install.yaml` or its
  password wrapper unless they explicitly choose the combined installer.
  State that HBN/hardware settings remain in separate stage files.
- Validate YAML rendering, commands, links and Markdown. When publication is
  authorized, commit/push and verify the remote revision before sharing Git links.
- When the user will run/test the commands, leave deployment to them.
- Keep real lab MAC addresses local; public templates have blank MAC fields.
- Keep passwords, tokens, private keys and kubeconfigs out of Git. Use
  `DPF/credentials.sh` for the BMC Secret. Respect instructions not to make backups.
- **Architecture:** external Argo is shared; DPF and NICo have separate entry files.
  Standalone DPF must work without NICo. Define ownership before NICo integration;
  never manage one resource through overlapping Applications. Keep DPF service
  Argo separate from external Argo. NICo Core GitOps is in `NICo/`; read its scope
  and validation limits before use.
- Teardown: drain services before tenant APIs; reclaim volumes before storage;
  verify retained CRDs separately. Preserve management Kubernetes and external
  Argo unless their deletion is explicitly requested.
- Keep customer deployment files here and NICo source/build work in its own repo.
  `build-host` (`192.0.2.23`) is build-only, never for lab administration.

## Lessons from the lab run of 2026-11-16 (two tenants, installer path)

Read these before any install, teardown or demo work in this repository.

- **Look before every mutating step.** The user also runs commands in the same
  session. Re-read the cluster (`kubectl get dpu,dpudeployment,dpuset,
  dpunodemaintenance,dpucluster -A`) right before each delete; never rely on a
  check made minutes earlier, and never chain several deletes in one command.
- **Teardown order is strict.** Per tenant: delete `dpudeployment.yaml`, wait until
  the DPU is gone, then the `4-dpu-install` folder, `3-hbn-network`,
  `2-dpu-cluster`. Second tenant before the first. `1-dpf-settings` and the BMC
  Secret go last, only when the check above prints nothing. Deleting the DPU
  cluster or the settings while a DPU, deployment or hold object exists removes
  the kubeconfig Secret or the controller DPF needs, and objects stay stuck in
  deletion (`secrets "dpu-cluster-<x>-admin-kubeconfig" not found`).
- **Stuck in deletion:** `./dpf-install.sh --clean` names the object and stops.
  `--clean --force-finalizers` releases only objects already marked for deletion.
  Removing a finalizer is the user's decision each time: state the object, why
  its finalizer can no longer finish, and ask. Approval for some objects does not
  cover others.
- **`--clean` refuses while any DPU object exists** ("used outside this lab",
  "Deprovision ... first"). That is the guard, not a fault. Add
  `--delete-storage` for an empty start (Kamaji etcd volumes).
- **`hold: true`** in `dpudeployment.yaml`: the object `dpu-node-<tenant>-hold`
  exists only after the hardware folder is applied and the DPU shows
  `Node Effect` (about 10 s). The release command fails before that.
- **`Pending` with two DPU clusters** (`hbn-lab`, `hbn-asia`,
  `ApplicationsReady=False`) is a DPF v26.4.0 status display. With one tenant
  `hbn-lab` shows `Success`. Judge by the BGP summary in the HBN pod (2 of 2 up) and the
  ping to the server (README steps 9 and 10). The DPU cluster VIP is not reachable from the admin host; that
  is also expected.
- **Measured times:** prerequisites 4 min, DPF operator 20 s, DPU cluster Ready
  71 s, hold release to `Rebooting` 24 min, host off 30 s, power on to DPU ping
  2 min (iDRAC still reads `Off` for some seconds), reboot-done to `Ready` 16 min.
- **Real values and passwords live in `DPF/internal/` and `DPF/dpu-lab/site/`**,
  both ignored by Git: run sheet `VIDEO-STEPS.md`, `DEMO-COMMANDS.txt`,
  `video-values.txt`, the real-value YAML and a cluster backup. Never copy them
  into tracked files. Before any push, check the tracked tree for real
  addresses, serial numbers and passwords.
- **Credentials:** the two server iDRACs use different passwords, and some
  password files in the parent `lab/private/` and `passwords` are stale. Test a
  login once (read-only Redfish GET) before relying on it; stop after one
  failure. When listing a credentials file, mask whole lines, not `key=value`
  patterns: a `user/password` line slipped through such a mask once.
- **Workbench:** `DPF/user-documentation/dpf-only-workbench-new.html` is the
  current page (intro + DPU 101 from the user's file, YAML and Edit/Provision/
  Add-a-tenant from the lab). Tenant names are the lab's: `lab` (VRF EUROPE,
  VNI 100001, AS 65101) and `asia` (VRF ASIA, VNI 100002, AS 65201). Check by
  content and size which HTML file is newer; a recent timestamp proved nothing.
- **Git:** work on `main` only; one tag `v1.0`. A plain clone gets `main`, so
  agree with the user before pushing to `main` after a release.
- **Not possible from an agent session here:** `gh`, package installs, `ssh`
  to other hosts, screen video. Say so early and give the user the command.

Package details: [DPF/Argo skill](.agents/skills/dsx-dpf-argo/SKILL.md).
The user's latest instructions take precedence over these defaults.
