import importlib.util
import pathlib
import subprocess
import unittest
from unittest.mock import patch
import json
import os
import tempfile
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT/'tools/installer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_crd_delete_allowlist_excludes_kubernetes_network_and_argo(self):
        names = installer.platform_crds()
        self.assertIn('dpus.provisioning.dpu.nvidia.com', names)
        self.assertIn('certificates.cert-manager.io', names)
        self.assertIn('tenantcontrolplanes.kamaji.clastix.io', names)
        self.assertFalse(any('projectcalico' in n or 'argoproj' in n for n in names))

    def test_delete_plan_requires_dependents_before_controllers_and_storage(self):
        steps = installer.DELETE_STEPS
        self.assertLess(steps.index('hardware'), steps.index('tenants'))
        self.assertLess(steps.index('tenants'), steps.index('volumes'))
        self.assertLess(steps.index('volumes'), steps.index('applications'))
        self.assertLess(steps.index('applications'), steps.index('crds'))
        self.assertLess(steps.index('crds'), steps.index('external-argo'))

    def test_menu_help_is_nonmutating(self):
        result = subprocess.run(['bash', str(ROOT/'install.sh'), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--config', result.stdout)
        self.assertIn('delete', result.stdout)

    def test_config_rejects_arbitrary_git_source(self):
        base = {'kind':'Application', 'metadata':{'name':'dpf','namespace':'argocd'},
                'spec': {'destination':{'name':'in-cluster','namespace':'dpf-operator-system'},
                         'sources':[{'repoURL':'https://bad.example/repo','path':'unexpected','targetRevision':'a'*40}]}}
        with self.assertRaises(ValueError): installer.validate_config(base)

    def test_protected_resource_scope(self):
        self.assertFalse(installer.in_scope_namespace('kube-system'))
        self.assertFalse(installer.in_scope_namespace('default'))
        self.assertTrue(installer.in_scope_namespace('dpf-operator-system'))
        self.assertTrue(installer.in_scope_namespace('tenant-europe'))

    def test_shared_argo_release_blocks_before_any_write(self):
        with patch.object(installer, 'objects', return_value=[]), \
             patch.object(installer, 'command', return_value='[{"name":"other-argo"}]'), \
             patch.object(installer, 'kube', return_value='lab') as kube:
            with self.assertRaisesRegex(RuntimeError, 'Unexpected Helm'):
                installer.delete_all('lab')
            self.assertEqual(kube.call_args_list, [unittest.mock.call('config', 'current-context')])

    def test_unrelated_project_blocks_teardown(self):
        def objects(resource, namespace=None):
            if resource == 'crds': return [{'metadata': {'name': 'appprojects.argoproj.io'}}]
            if resource == 'appprojects.argoproj.io':
                return [{'metadata': {'namespace': 'argocd', 'name': 'customer'}}]
            return []
        with patch.object(installer, 'objects', side_effect=objects), \
             patch.object(installer, 'command', return_value='[]'):
            with self.assertRaisesRegex(RuntimeError, 'AppProject'):
                installer.inventory()

    def test_different_storage_provisioner_blocks_teardown(self):
        def objects(resource, namespace=None):
            if resource == 'storageclasses':
                return [{'metadata': {'name': 'local-path'}, 'provisioner': 'other.example/storage'}]
            return []
        with patch.object(installer, 'objects', side_effect=objects), \
             patch.object(installer, 'command', return_value='[]'):
            with self.assertRaisesRegex(RuntimeError, 'provisioner'):
                installer.inventory()

    def test_application_cleanup_preserves_existing_finalizers(self):
        app = {'metadata': {'namespace': 'argocd', 'name': 'dpf', 'finalizers': ['example.org/protect']}}
        with patch.object(installer, 'inventory', return_value=(set(), [app], [])), \
             patch.object(installer, 'DELETE_STEPS', ['applications']), \
             patch.object(installer, 'objects', return_value=[]), \
             patch.object(installer, 'kube', return_value='lab') as kube:
            installer.delete_all('lab')
        payloads = [json.loads(call.args[-1]) for call in kube.call_args_list if 'patch' in call.args]
        finalizers = next(p['metadata']['finalizers'] for p in payloads if 'metadata' in p)
        self.assertIn('example.org/protect', finalizers)
        self.assertIn('resources-finalizer.argocd.argoproj.io', finalizers)

    def test_cleanup_stops_after_first_delete_failure(self):
        def kube(*args):
            if args == ('config', 'current-context'): return 'lab'
            raise RuntimeError('simulated controller timeout')
        with patch.object(installer, 'inventory', return_value=(set(), [], [])), \
             patch.object(installer, 'kube', side_effect=kube) as calls:
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                installer.delete_all('lab')
        self.assertFalse(any('crd' in call.args for call in calls.call_args_list))

    def test_shared_prerequisite_instances_block_before_writes(self):
        for crd, obj in [
            ('nodefeatures.nfd.k8s-sigs.io', {'kind': 'NodeFeature', 'metadata': {'name': 'node1', 'namespace': 'other'}}),
            ('nodemaintenances.maintenance.nvidia.com', {'kind': 'NodeMaintenance', 'metadata': {'name': 'foreign'}}),
            ('certificaterequests.cert-manager.io', {'kind': 'CertificateRequest', 'metadata': {'name': 'other', 'namespace': 'default'}}),
        ]:
            def objects(resource, namespace=None):
                if resource == 'crds': return [{'metadata': {'name': crd}}]
                if resource == crd: return [obj]
                return []
            with self.subTest(crd=crd), patch.object(installer, 'objects', side_effect=objects), \
                 patch.object(installer, 'command', return_value='[]'):
                with self.assertRaisesRegex(RuntimeError, 'outside|unrecognized'):
                    installer.inventory()

    def test_orphaned_platform_resource_stops_cleanup(self):
        resource = {'kind': 'StorageClass', 'metadata': {'name': 'local-path', 'annotations': {
            'argocd.argoproj.io/installation-id': 'dsx-platform',
            'argocd.argoproj.io/tracking-id': 'dpf-platform:storage.k8s.io/StorageClass:/local-path'}}}
        with patch.object(installer, 'platform_cluster_resources', return_value=[resource]):
            with self.assertRaisesRegex(RuntimeError, 'orphaned'):
                installer.verify_cluster_ownership([])
            installer.verify_cluster_ownership([{'metadata': {'namespace': 'argocd', 'name': 'dpf-platform'}}])

    def test_cluster_snapshot_pins_both_tools_and_removes_private_file(self):
        snapshot = json.dumps({'current-context': 'lab', 'clusters': [], 'contexts': [], 'users': []})
        response = subprocess.CompletedProcess([], 0, snapshot, '')
        previous = os.environ.get('KUBECONFIG')
        with patch.object(installer.subprocess, 'run', return_value=response) as run:
            with installer.pinned_cluster('lab'):
                path = pathlib.Path(os.environ['KUBECONFIG'])
                self.assertEqual(path.read_text(), snapshot)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertIn('--flatten', run.call_args.args[0])
                self.assertIn('lab', run.call_args.args[0])
                # kubectl and Helm inherit this same file even if the user's default changes.
                self.assertNotEqual(str(path), previous)
            self.assertFalse(path.exists())
        self.assertEqual(os.environ.get('KUBECONFIG'), previous)

    def test_all_stops_before_credentials_when_helm_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            log = root/'commands'
            for tool in ['helm', 'kubectl']:
                stub = root/tool
                stub.write_text('#!/bin/sh\necho "' + tool + ' $*" >> "$TEST_COMMAND_LOG"\nexit 7\n')
                stub.chmod(0o700)
            sources = [{'repoURL': 'https://github.com/kirson-git/dsx-os.git', 'path': p,
                        'targetRevision': 'a'*40} for p in installer.SOURCE_PATHS]
            sources[1]['helm'] = {'valuesObject': {}}
            app = {'kind': 'Application', 'metadata': {'name': 'dpf', 'namespace': 'argocd'},
                   'spec': {'destination': {'name': 'in-cluster', 'namespace': 'dpf-operator-system'},
                            'sources': sources, 'syncPolicy': {'syncOptions': ['FailOnSharedResource=true']}}}
            config = root/'install.yaml'; config.write_text(yaml.safe_dump(app))
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'], TEST_COMMAND_LOG=str(log))
            result = subprocess.run(['bash', str(ROOT/'install.sh'), '--config', str(config), '--action', 'all'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            self.assertEqual(log.read_text().splitlines(), ['helm repo add argo https://argoproj.github.io/argo-helm'])
