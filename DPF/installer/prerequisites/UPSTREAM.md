# Prerequisite source provenance

`helmfiles/` is copied unchanged from `deploy/helmfiles/` in
[NVIDIA/doca-platform v26.4.0](https://github.com/NVIDIA/doca-platform/tree/v26.4.0/deploy/helmfiles),
commit `8551df0d3ac4ed51a67d4a5148a7646493a30e10`.
`LICENSE.dpf` accompanies that source. The authoritative installation guide is
[NVIDIA Helm prerequisites](https://networking-docs.nvidia.com/dpf/26.4.0/helm-prerequisites).

`charts/local-path-provisioner/` is copied from `deploy/chart/local-path-provisioner/`
in [rancher/local-path-provisioner v0.0.34](https://github.com/rancher/local-path-provisioner/tree/v0.0.34/deploy/chart/local-path-provisioner),
commit `af49f3fdf69e2e5ad790d295b6005ba3767ec991`.
`charts/LICENSE.local-path` accompanies that source.

## Adaptations applied only to each run's copy

- Remove the local-path release when reusing an existing StorageClass. Existing
  provisioner versions are accepted, as requested for this lab.
- Otherwise use the bundled v0.0.34 chart instead of the same upstream Git chart
  URL. Remove the unused `local-storage` repository in either case. This avoids
  the helm-git plugin without changing the chart content or values.
- When installing local-path, add it to Kamaji's `needs` list so storage installs
  before etcd.
- Apply the selected release timeout, keeping individual hook timeouts intact.
- If reusing a custom StorageClass, append only the Kamaji etcd class override.

All other prerequisite values, release versions and hooks remain from upstream.
The monitoring Helmfile is included for provenance but is never executed by
`--install-prereq`. Helmfile `apply` preserves pre-apply hooks; switching this to
`sync` without accounting for hook semantics would change the workflow.

## Validation boundary

The wrapper has automated tests for existing/missing storage, failed API reads,
dry-run behavior, context selection and failure propagation. The lab dry-run and
Helmfile parsing are exercised without installing anything. Offline rendering of
the component charts is not proof of live webhook bootstrap or storage readiness.

## Kamaji bootstrap

When `default` is absent, or retained after a missing/failed Kamaji release,
`kamaji_bootstrap.py` creates a separate run-local
Helmfile with `defaultDatastoreName: ""` and
`kamaji-etcd.datastore.enabled: false`. These settings come from the pinned Kamaji
1.2.0 chart's `values.yaml`, `templates/controller.yaml` and
`charts/kamaji-etcd/templates/etcd_datastore.yaml`. The bootstrap waits for the
controller/webhook and etcd, creates the chart-rendered DataStore with Helm
release ownership metadata (or reuses a retained object with matching ownership),
then reconciles the unchanged final NVIDIA values.
No admission failure policy is changed. Existing tenant control planes and
unfinished Helm operations block automatic bootstrap.
