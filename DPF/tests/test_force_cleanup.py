import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import installer


class ImmediateCleanupTests(unittest.TestCase):
    def test_force_delete_strips_finalizers_and_never_waits(self):
        obj = {'kind': 'DPU', 'metadata': {'name': 'asia', 'namespace': 'dpf-operator-system',
                                        'uid': 'device-uid', 'finalizers': ['dpf/finalizer']}}
        with patch.object(installer, 'kube', return_value='') as kube, \
             patch.object(installer, 'resource_endpoint', return_value='/apis/provisioning.dpu.nvidia.com/v1alpha1/namespaces/dpf-operator-system/dpus/asia'), \
             patch.object(installer, 'command') as command:
            installer.force_remove('dpus.provisioning.dpu.nvidia.com', obj)
        calls = [c.args for c in kube.call_args_list]
        patch_payload = json.loads(calls[0][-1])
        self.assertEqual(patch_payload[0], {'op': 'test', 'path': '/metadata/uid', 'value': 'device-uid'})
        self.assertIn({'op': 'add', 'path': '/metadata/finalizers', 'value': []}, patch_payload)
        deletion = json.loads(command.call_args.kwargs['input'])
        self.assertEqual(deletion['preconditions'], {'uid': 'device-uid'})
        self.assertEqual(deletion['gracePeriodSeconds'], 0)
        self.assertIn('--raw', command.call_args.args[0])
        self.assertFalse(any('wait' in c for c in calls))

    def test_force_delete_rejects_protected_namespace(self):
        obj = {'kind': 'Pod', 'metadata': {'name': 'dns', 'namespace': 'kube-system', 'uid': 'x'}}
        with patch.object(installer, 'kube') as kube:
            with self.assertRaisesRegex(RuntimeError, 'scope'):
                installer.force_remove('pods', obj)
            kube.assert_not_called()

    def test_force_delete_rejects_external_argo_crd(self):
        obj = {'kind': 'CustomResourceDefinition', 'metadata': {'name': 'applications.argoproj.io', 'uid': 'x'}}
        with patch.object(installer, 'kube') as kube:
            with self.assertRaisesRegex(RuntimeError, 'scope'):
                installer.force_remove('crds', obj)
            kube.assert_not_called()

    def test_orphaned_known_owner_is_allowed_only_in_brutal_mode(self):
        obj = {'kind': 'StorageClass', 'metadata': {'name': 'local-path', 'annotations': {
            'argocd.argoproj.io/installation-id': 'dsx-platform',
            'argocd.argoproj.io/tracking-id': 'dpf-platform:storage.k8s.io/StorageClass:/local-path'}}}
        with patch.object(installer, 'platform_cluster_resources', return_value=[obj]):
            with self.assertRaises(RuntimeError): installer.verify_cluster_ownership([])
            installer.verify_cluster_ownership([], allow_orphaned=True)
            obj['metadata']['annotations']['argocd.argoproj.io/tracking-id'] = 'other:kind:/name'
            with self.assertRaises(RuntimeError): installer.verify_cluster_ownership([], allow_orphaned=True)

    def test_force_entrypoint_never_uses_wait_and_preserves_argo(self):
        app = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
               'metadata': {'name': 'dpf', 'namespace': 'argocd', 'uid': 'app'}}
        dpu = {'apiVersion': 'provisioning.dpu.nvidia.com/v1alpha1', 'kind': 'DPU',
               'metadata': {'name': 'asia', 'namespace': 'dpf-operator-system', 'uid': 'dpu', 'finalizers': ['stuck']}}
        crd_name = 'dpus.provisioning.dpu.nvidia.com'
        crd = {'kind': 'CustomResourceDefinition', 'apiVersion': 'apiextensions.k8s.io/v1',
               'metadata': {'name': crd_name, 'uid': 'crd'}}
        def objects(resource, namespace=None):
            if resource == 'crds': return [crd]
            if resource == crd_name: return [dpu]
            return []
        def kube(*args):
            if args == ('config', 'current-context'): return 'lab'
            return ''
        with patch.object(installer, 'inventory', return_value=({crd_name}, [app], [])), \
             patch.object(installer, 'platform_cluster_resources', return_value=[]), \
             patch.object(installer, 'objects', side_effect=objects), \
             patch.object(installer, 'kube', side_effect=kube) as calls, \
             patch.object(installer, 'resource_endpoint', side_effect=lambda o: '/test/' + o['metadata']['name']), \
             patch.object(installer, 'command') as command, \
             patch.object(installer.time, 'sleep', side_effect=AssertionError('must not wait')):
            installer.immediate_delete('lab')
        deletes = [c.args[0] for c in command.call_args_list]
        self.assertEqual([c[4] for c in deletes], ['/test/dpf', '/test/asia', '/test/' + crd_name])
        for call in command.call_args_list:
            options = json.loads(call.kwargs['input'])
            self.assertEqual(options['gracePeriodSeconds'], 0)
            self.assertTrue(options['preconditions']['uid'])
        self.assertFalse(any('wait' in c.args for c in calls.call_args_list))

    def test_endpoint_uses_api_discovery_plural(self):
        installer.api_resource_names.cache_clear()
        response = json.dumps({'resources': [{'kind': 'DPU', 'name': 'dpus'}, {'kind': 'DPU', 'name': 'dpus/status'}]})
        with patch.object(installer, 'kube', return_value=response):
            endpoint = installer.resource_endpoint({'apiVersion': 'provisioning.dpu.nvidia.com/v1alpha1',
                'kind': 'DPU', 'metadata': {'name': 'asia', 'namespace': 'dpf-operator-system'}})
        self.assertEqual(endpoint, '/apis/provisioning.dpu.nvidia.com/v1alpha1/namespaces/dpf-operator-system/dpus/asia')
        installer.api_resource_names.cache_clear()
