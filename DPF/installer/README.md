# DPF checks and installer

`dpf-install.sh` checks a cluster, then installs the DPF prerequisites and the
DPF v26.4.0 operator with Helm. It is an alternative to the Argo CD steps in
the [main guide](../README.md). Use one of the two on a cluster, not both:
they install the same components.

Needs Bash, kubectl, Helm and Python 3 with PyYAML. Installing also needs
helmfile and jq.

## Steps

Run every command from the `DPF/` folder.

1. Check the cluster. Nothing is installed.

   ```bash
   ./dpf-install.sh --sanity --prereq
   ./dpf-install.sh --sanity --hardware
   ```

2. Preview, then install the prerequisites.

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
   ```

5. Test BMC access, then store the BMC password. The password is typed at a
   prompt and is not written to a file.

   ```bash
   ./dpf-install.sh --check-bmc
   python3 installer/lab/create-bmc-secret.py --context "$(kubectl config current-context)"
   ```

`./dpf-install.sh --help` lists every action and option.

## What each action does to the cluster

| Action | Effect |
| --- | --- |
| `--sanity --prereq`, `--sanity --hardware`, `--verify`, `--diagnose` | Reads only |
| Any action with `--dry-run`, and `--clean` without `--yes` | Preview only |
| `--sanity --storage`, `--sanity --nics`, `--check-bmc`, `--discover-dpus` | Creates temporary pods or a small test volume, then removes them |
| `--install-prereq`, `--install-dpf` | Installs Helm releases |
| `--clean --yes` | Deletes the DPF installation shown in the preview |

## After the operator

The installer stops at the operator. The tenant cluster, HBN and DPU
provisioning use the YAML files under
[`profiles/two-tenant-hbn/desired/`](../profiles/two-tenant-hbn/README.md).
Replace the example addresses and hardware identities there before applying
them.

## Files the installer writes

Logs go to `installer/logs/` and working files to `installer/state/`. Git
ignores both. Do not commit them: they can contain addresses of your site.

## Status

This tool was added to the repository on 2026-11-11 from the lab where it was
written. From this location only the `--help` output has been exercised. Run
the checks in step 1 before relying on the install actions.
