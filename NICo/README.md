# NICo + DPF

This directory is reserved for the NICo-integrated stack. Implementation and
clean-install qualification are pending. Use [standalone DPF](../DPF/README.md)
for the package provided by this repository revision.

## Planned ownership

External platform Argo CD will install NICo, its prerequisites, the compatible
DPF operator and DPF prerequisites. NICo will own the inventory and provisioning
resources that its integration generates. DPF and its service Argo will reconcile
DPU provisioning and service delivery.

Do not sync the standalone DPF inventory, DPUSet or DPUDeployment example over
NICo-generated resources. Changing stacks is an ownership migration, not simply
installing another chart beside the standalone profile.

## Before this path becomes installable

- Pin the NICo release and verify its supported DPF, Kubernetes and firmware matrix.
- Publish and verify required NICo images and boot artifacts.
- Add NICo database, DHCP/PXE, DNS, registry and secret-management configuration.
- Define the NICo-to-DPF ownership boundary and standalone migration procedure.
- Test hardware discovery, provisioning, tenant lifecycle, network isolation,
  recovery and cleanup through the external Argo workflow.

No NICo installer or release compatibility claim is included yet.
