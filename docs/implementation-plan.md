# External Argo DPF recovery package implementation plan

> Execute inline with superpowers:executing-plans. The installation guide targets
> a clean Kubernetes cluster; live teardown and rebuild remain separate tasks.

**Goal:** Install prerequisites and DPF with external Argo, reproduce the two-tenant
HBN setup, and document customer production changes without publishing credentials.

**Architecture:** External Argo owns the platform and root custom resources.
A distinct service Argo in dpf-operator-system owns DPF-generated Applications.
Same-cluster installations have one shared Argo CRD owner; separate clusters need
CRDs on both. The sample profile is a sanitized model of the saved working lab.

**Tech stack:** Pinned DPF 26.4.0 charts, Argo Helm 9.4.1, Python, Helm, YAML.

**Spec:** User requirements recorded in this plan; inherited chart adaptations
and provenance are in ../DPF/SOURCES.txt.

## Constraints and review focus

- Never commit credentials, private keys, kubeconfigs or raw live snapshots.
- Keep controller namespaces, installation IDs and Application ownership distinct.
- Keep generated DPF children outside external Argo desired state.
- Offer one automatic full-stack Application or separate manual stages;
  document that either can reimage hardware when provisioning begins.
- Record unsupported/recovery steps and qualification honestly.

## Tasks

- [x] Capture private lab roots, Helm overrides, host/fabric settings and evidence.
- [x] Verify the inherited chart renderer baseline (22 tests).
- [x] Add external renderer and tests for Argo ownership, CRD placement and hooks.
- [x] Include sanitized Europe/Asia profile, host networking and fabric contract.
- [x] Document bootstrap, dependency ordering, verification and production inputs.
- [x] Render both topology variants; validate CRDs and resource uniqueness.
- [x] Scan the complete proposed Git payload and publish to kirson-git/dsx-os.
- [x] Record the clean-cluster starting point, including removal of old CRDs.
- [ ] Finalize the exact live deletion inventory before teardown.
- [ ] Complete private recovery including credentials, tenant data and fabric state.
- [ ] Preview exact teardown, then perform the agreed teardown with command logs.
- [ ] Rebuild from external Argo and repeat both-tenant data-path acceptance checks.

A passing renderer or dry-run is not a successful clean rebuild. Runtime tasks
remain pending until performed, including reboot persistence and isolation tests.

User clarification: Argo installation uses standard Helm commands, followed by
Application YAMLs. No custom bootstrap wrapper ships. Passwords are external,
with a private-input BMC helper and documented external-secret-manager option.

Clean-cluster clarification: bootstrap Helm installs fresh Argo CRDs. The external
installation retains its distinct installation ID; the later service Argo omits
shared CRDs. The guide lists all five Application YAMLs and their sync order.

User refinement: support both one-file and separate-stage deployment using the
same manifests. Supply credentials with a Bash helper; document BMC IP/password
separately from DPU Arm OS management IP/SSH credentials and HBN data pools.
