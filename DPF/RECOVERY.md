# Teardown and recovery boundary

Objective: remove the agreed DPF stack, bootstrap external Argo, and restore the
standalone two-tenant HBN outcome. The installation guide assumes a clean
Kubernetes cluster after removal of the previous stack and its CRDs. No cleanup
has been run by publishing this package; Kubernetes must remain operational or
be rebuilt separately before following the installation steps.

## Before deleting

1. Record cluster identity, namespace/release inventory and resource ownership.
2. Preserve a private, verified recovery bundle: root CRs, installed Helm values,
   versions, tenant data and required certificates/credentials, host configuration,
   switch/router running configuration and command logs. Public examples are not
   a backup of runtime state or secrets.
3. Choose whether tenant etcd/PVCs are retained or rebuilt. Retained data requires
   matching identities/certificates; a new cluster must not reuse stale kubeconfigs.
4. Separate dedicated prerequisites from services shared with other workloads.
5. Decide explicitly whether DPUs are reprovisioned. Deleting provisioning resources
   can trigger hardware cleanup; do not assume it leaves their OS/services intact.
6. Preserve management Kubernetes, host disks, network access and fabric unless
   those are explicitly included in the teardown scope.

## Teardown sequencing

Stop conflicting GitOps reconciliation first. Remove intended root provisioning
and service resources while their DPF controllers can complete lifecycle/finalizer
work. Wait for and inspect cleanup before removing tenant control planes. Keep
Kamaji and its datastore available until tenant cleanup is complete. Remove DPF
configuration/operator and dedicated prerequisites only after dependent resources
are gone. Do not strip finalizers to make a failed cleanup appear successful.

Argo Application deletion is non-cascading in these templates. Removing an
Application therefore does not uninstall the resources it managed. Chart-rendered
resources are also not Helm releases: do not expect `helm uninstall` to remove
Argo-applied workloads. Produce the exact environment-specific deletion list from
owned resources and review storage/hardware consequences before executing it.

For a partial teardown, shared cert-manager, storage, NFD or Argo CRDs must not
be deleted merely because they appear in a DPF list. An existing deployment is
an ownership migration, not a fresh install; manual sync and FailOnSharedResource
do not detect every Helm-owned
or untracked resource. Do not apply this package over the working stack blindly.

## Return to the saved outcome

Follow the installation README, restore reviewed site/hardware inputs and private
credentials, complete external reboot/node-effect handling, and ensure fabric and
host bootstrap are present. Validate both tenant APIs, DPUs, HBN pods, BGP/EVPN,
Ubuntu data-path Internet access and isolation. Capture exact command logs and
compare with the private pre-teardown evidence.

Keep a recovery path until reboot persistence, data-path checks and the intended
isolation checks pass. A successful manifest dry-run or Argo Synced status alone
does not establish this outcome.

## Argo CRDs after a full reset

For the agreed clean-cluster path, the previous Argo CRDs are gone. Install
external Argo with CRD installation enabled (the chart default), exactly as in
the main README. The later DPF service Argo reuses these newly installed CRDs.

Reusing existing Argo CRDs is a different migration path: it can require
`--set crds.install=false`, schema compatibility checks and preserving their
owner. That flag is not part of the clean-cluster installation command.
