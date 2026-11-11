# Installer modules

The layout follows the [Run:ai installer](https://github.com/runai-professional-services/runai-installer/tree/16b69974b951a0a1d292e8a206f6d262db241bd4)
conventions: a small root entrypoint, feature modules, shared logging, tools and
separate sanity checks. The implementation remains specific to DPF/NICo.

| Location | Responsibility |
| --- | --- |
| `dpf-install.sh` | Stable public entrypoint. |
| `modules/main.sh` | Argument validation and action dispatch. |
| `modules/menu.sh` | Interactive action selection; existing numbers are preserved. |
| `modules/common.sh` | Resolve and export `DPF_INSTALLER_DIR`; no cluster actions. |
| `modules/log.sh` | Shared command logging and colored messages. |
| `modules/prerequisites.sh` | NVIDIA prerequisite orchestration, sourced by main. |
| `modules/dpf.sh` | Standalone DPF operator installation. |
| `modules/settings.sh` | Lab settings questionnaire. |
| `modules/bmc.sh` | BMC access check entrypoint. |
| `modules/discovery.sh` | Guided Kubernetes BMC range discovery entrypoint. |
| `modules/uninstall.sh` | DPF lab cleanup entrypoint. |
| `tools/` | Python implementation and shared presentation. |
| `sanity-check/` | Diagnostic entrypoint and check modules. |

Root Python names and older shell entrypoints are compatibility symlinks, not
duplicate implementations. They keep existing commands and older installer
sessions working. New code uses canonical paths under `modules/` and `tools/`.

## Adding a module

1. Add its Bash entrypoint under `modules/` and supporting Python under `tools/`.
2. Source `common.sh` to resolve the installation directory; source `log.sh` for
   install phases. Keep arguments as arrays. Do not use `eval` or shell tracing.
3. Add public flags and validation in `main.sh`, then add the action to
   `menu.sh` and the labels in `tools/ui.py`. Keep existing menu numbers stable.
4. Follow `dpf.sh` for preflight, private run directory, audit initialization,
   EXIT status recording and cleanup. All generated files belong in `state/`.
5. Call `log_command DESCRIPTION OUTPUT_FILE EXECUTABLE [ARGUMENTS...]` after
   initializing `DPF_INSTALL_LOG`. It returns the command's exit status and saves
   stdout/stderr in the phase file and unified log. `log_message MESSAGE [LEVEL]`
   uses INFO by default; supported levels are INFO, SUCCESS, WARNING and ERROR.
6. Document side effects, CLI arguments and ownership boundaries. Test the module
   with mocked tools, including failures, before a separate live installation.

## NICo integration boundary

NICo v2.1.4 installation is planned, not implemented by these entrypoints. The
shared module architecture is ready for it; there is no placeholder install
button that reports success. Standalone DPF remains the implemented workflow.

The NICo module must explicitly select NICo-managed DPF configuration rather than
reuse standalone lab settings implicitly. Its design must cover pinned NICo and
DPF compatibility, image registry access, database settings, service VIPs and
routing, BMC access, DHCP/PXE and ownership of DPF runtime objects. DPF hardware,
storage, NIC and BMC checks can be reused as individual checks; passing them is
not proof that NICo is ready. NICo installation and cleanup need separate scope
and checks so a DPF action cannot silently remove NICo resources.
