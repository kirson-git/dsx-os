# Install DPF with `dpf-install.sh`

Installs the DPF prerequisites and the DPF v26.4.0 operator with Helm/Helmfile.
It is an **alternative** to the Argo CD steps in the [Argo guide](../argo/README.md):
use one or the other on a cluster, not both.
This does not install tenants, HBN or DPU provisioning; those are separate stages.

Needs Bash, kubectl, Helm, helmfile, jq and Python 3 with PyYAML
(all present on the administration server).

## Run (from the `DPF/` folder)

1. Check the cluster. Read-only.

   ```bash
   ./dpf-install.sh --sanity --prereq
   ./dpf-install.sh --sanity --hardware
   ```

2. Preview, then install the prerequisites
   (cert-manager, Argo CD, Node Feature Discovery, Maintenance Operator, Kamaji).

   ```bash
   ./dpf-install.sh --install-prereq --dry-run
   ./dpf-install.sh --install-prereq
   ```

3. Preview, then install the DPF operator.

   ```bash
   ./dpf-install.sh --install-dpf --dry-run
   ./dpf-install.sh --install-dpf
   ```

4. Verify. Every row must be installed, ready and at the expected version.

   ```bash
   ./dpf-install.sh --verify
   ./dpf-install.sh --diagnose   # only if something is not ready
   ```

## Notes for this lab

- The cluster has **no StorageClass**. The installer adds the bundled
  local-path provisioner (v0.0.34) for Kamaji etcd. Use `--storage-class NAME`
  to reuse an existing class instead.
- Logs: `logs/latest.log` and `logs/latest/`. Temporary files: `state/`.
- Exit codes: install `0` success, `2` usage error, other nonzero on failure.
  Failures stop the run; nothing is uninstalled automatically.
- Cleanup preview: `./dpf-install.sh --clean` (add `--yes` to execute).

## Run record

Fill in after the run.

| Step | Date/time | Result | Notes |
| --- | --- | --- | --- |
| sanity --prereq | 2026-11-15 18:32 | Pass | All components installed, ready, version match |
| sanity --hardware | 2026-11-15 18:32 | Pass | 3 control-plane nodes, 24 CPU each, no pressure |
| install-prereq | 2026-11-15 18:32 | Not run | Already installed (sanity shows all Match) |
| install-dpf | 2026-11-15 18:32 | Not run | dpf-operator v26.4.0 already installed and Ready |
| verify | 2026-11-15 18:32 | Pass | Every row installed, ready, version match; exit 0 |

Issues and fixes:

- None. The install steps were skipped because the cluster already had everything at the expected versions.
