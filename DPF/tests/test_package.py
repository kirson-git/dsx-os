import copy
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('render', ROOT / 'tools/render.py')
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)

class PackageTests(unittest.TestCase):
    def config(self):
        return {'git': {'repoURL': 'https://git.example.com/team/dpf.git', 'revision': 'main', 'path': 'rendered'},
                'argoNamespace': 'dpf-operator-system', 'kubernetesVersion': '1.34.0',
                'storage': {'installLocalPath': True, 'className': 'local-path'},
                'operator': {'enabled': True, 'mode': 'zero-trust', 'apiServerHost': '192.0.2.10', 'apiServerPort': 6443}}
    def test_invalid_input_fails_before_render(self):
        for section, key, value in [('git','repoURL','https://user:secret@host/repo'),
                                    ('git','path','../private'), ('operator','apiServerHost',''),
                                    ('operator','apiServerPort',0), ('operator','mode','nic'),
                                    ('storage','installLocalPath','false')]:
            with self.subTest(key=key):
                cfg=self.config();cfg[section][key]=value
                with self.assertRaises(ValueError):render.validate(cfg)
    def test_default_local_storage_cannot_use_other_name(self):
        cfg=self.config();cfg['storage']['className']='fast'
        with self.assertRaises(ValueError):render.validate(cfg)
    def test_config_preserves_zero_trust_and_argo_namespace(self):
        cfg=self.config();cfg['argoNamespace']='argocd'
        obj=render.operator_config(cfg)
        self.assertTrue(obj['spec']['dpuDetector']['disable'])
        self.assertEqual(obj['spec']['overrides']['argoCDNamespace'],'argocd')
        self.assertEqual(obj['spec']['overrides']['kubernetesAPIServerVIP'],'192.0.2.10')
    def test_host_trusted_does_not_enable_redfish(self):
        cfg=self.config();cfg['operator']['mode']='host-trusted';cfg['operator']['apiServerHost']=''
        render.validate(cfg)
        self.assertNotIn('installInterface',render.operator_config(cfg)['spec']['provisioningController'])
    def test_hook_translation_retains_rbac_and_disables_delete_job(self):
        for kind in ['ServiceAccount','ClusterRole','ClusterRoleBinding','ConfigMap']:
            obj={'kind':kind,'metadata':{'name':'kamaji-etcd','annotations':{'helm.sh/hook':'pre-install,post-install,pre-delete'}}}
            out=render.prepare_object(obj,'kamaji',30)
            self.assertNotIn('argocd.argoproj.io/hook',out['metadata']['annotations'])
            self.assertEqual(out['metadata']['annotations']['argocd.argoproj.io/sync-wave'],'20')
        obj={'kind':'Job','metadata':{'name':'delete','annotations':{'helm.sh/hook':'pre-delete'}}}
        self.assertIsNone(render.prepare_object(obj,'kamaji',30))
    def test_kamaji_jobs_run_at_correct_waves_and_remain_diagnosable(self):
        for name,hook,wave in [('kamaji-etcd-setup-1','pre-install','21'),('kamaji-etcd-setup-2','post-install','31')]:
            obj={'kind':'Job','metadata':{'name':name,'annotations':{'helm.sh/hook':hook}}}
            out=render.prepare_object(obj,'kamaji',30)
            ann=out['metadata']['annotations']
            self.assertEqual(ann['argocd.argoproj.io/sync-wave'],wave)
            self.assertEqual(ann['argocd.argoproj.io/hook'],'Sync')
            self.assertEqual(ann['argocd.argoproj.io/hook-delete-policy'],'BeforeHookCreation')
    def test_datastore_and_crd_waves(self):
        for kind,wave in [('CustomResourceDefinition','-20'),('DataStore','32')]:
            obj={'kind':kind,'metadata':{'name':'default'}}
            out=render.prepare_object(obj,'kamaji',30)
            self.assertEqual(out['metadata']['annotations']['argocd.argoproj.io/sync-wave'],wave)
    def test_crds_use_ssa_even_for_kubectl_triggered_syncs(self):
        obj={'kind':'CustomResourceDefinition','metadata':{'name':'large.example.com',
             'annotations':{'helm.sh/resource-policy':'keep'}}}
        out=render.prepare_object(obj,'test',0)
        options=out['metadata']['annotations']['argocd.argoproj.io/sync-options'].split(',')
        for option in ['ServerSideApply=true','Delete=false','Prune=false']:
            self.assertIn(option,options)

    def test_secret_material_is_rejected(self):
        for obj in [{'kind':'Secret','metadata':{'name':'oops'},'data':{'password':'eA=='}},
                    {'kind':'Secret','metadata':{'name':'oops'},'stringData':{'password':'x'}}]:
            with self.assertRaises(ValueError):render.prepare_object(obj,'test',0)
    def test_unknown_hooks_fail_closed(self):
        with self.assertRaises(ValueError):render.prepare_object({'kind':'Job','metadata':{'name':'unknown','annotations':{'helm.sh/hook':'pre-upgrade'}}},'operator',40)
    def test_application_disables_pruning_and_uses_current_cluster(self):
        app=render.application(self.config())
        self.assertEqual(app['spec']['destination']['server'],'https://kubernetes.default.svc')
        self.assertFalse(app['spec']['syncPolicy']['automated']['prune'])
        self.assertNotIn('finalizers',app['metadata'])
        self.assertIn('ServerSideApply=true',app['spec']['syncPolicy']['syncOptions'])


class RenderedChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.temp=tempfile.TemporaryDirectory()
        cls.cfg=PackageTests().config()
        cls.objects=render.render(cls.cfg,pathlib.Path(cls.temp.name)/'rendered')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_storage_controller_matches_standard_existing_class(self):
        storage=next(o for o in self.objects if o['kind']=='StorageClass')
        controller=next(o for o in self.objects if o['kind']=='Deployment' and o['metadata']['name']=='local-path-provisioner')
        command=controller['spec']['template']['spec']['containers'][0]['command']
        self.assertEqual(storage['provisioner'],'rancher.io/local-path')
        self.assertEqual(command[command.index('--provisioner-name')+1],storage['provisioner'])

    def test_custom_objects_match_bundled_crd_schemas(self):
        import jsonschema
        schemas={}
        for obj in self.objects:
            if obj['kind']=='CustomResourceDefinition':
                for version in obj['spec']['versions']:
                    schemas[(obj['spec']['group']+'/'+version['name'],obj['spec']['names']['kind'])]=version['schema']['openAPIV3Schema']
        checked=[]
        for obj in self.objects:
            schema=schemas.get((obj['apiVersion'],obj['kind']))
            if schema:
                jsonschema.Draft7Validator(schema).validate(obj);checked.append(obj['kind'])
        for kind in ['DPFOperatorConfig','DataStore','MaintenanceOperatorConfig','NodeFeatureRule','Certificate','Issuer']:
            self.assertIn(kind,checked)
    def test_dependencies_have_strictly_later_waves(self):
        def wave(kind,name):
            obj=next(o for o in self.objects if o['kind']==kind and o['metadata']['name']==name)
            return int(obj['metadata']['annotations']['argocd.argoproj.io/sync-wave'])
        self.assertLess(wave('Job','kamaji-etcd-setup-1'),wave('StatefulSet','kamaji-etcd'))
        self.assertLess(wave('StatefulSet','kamaji-etcd'),wave('Job','kamaji-etcd-setup-2'))
        self.assertLess(wave('Job','kamaji-etcd-setup-2'),wave('DataStore','default'))
        self.assertLess(wave('DataStore','default'),wave('Deployment','dpf-operator-controller-manager'))
        self.assertLess(wave('Deployment','dpf-operator-controller-manager'),wave('DPFOperatorConfig','dpfoperatorconfig'))
        maint=next(o for o in self.objects if o['kind']=='MaintenanceOperatorConfig')
        self.assertEqual(maint['metadata']['annotations']['argocd.argoproj.io/sync-wave'],'41')
    def test_no_secret_data_and_no_helm_hooks(self):
        for obj in self.objects:
            self.assertFalse(obj['kind']=='Secret' and (obj.get('data') or obj.get('stringData')))
            self.assertFalse(any(k.startswith('helm.sh/hook') for k in obj['metadata']['annotations']))
    def test_bootstrap_loop_broken_without_disabling_webhooks(self):
        deployment=next(o for o in self.objects if o['kind']=='Deployment' and o['metadata']['name']=='kamaji')
        args=deployment['spec']['template']['spec']['containers'][0]['args']
        self.assertFalse(any(a.startswith('--datastore=') for a in args))
        self.assertEqual(deployment['spec']['replicas'],2)
        for obj in self.objects:
            if obj['kind']=='ValidatingWebhookConfiguration' and 'kamaji' in obj['metadata']['name']:
                policies={w['name']:w['failurePolicy'] for w in obj['webhooks']}
                self.assertEqual(policies['vdatastore.kb.io'],'Fail')
                self.assertEqual(policies['vtenantcontrolplane.kb.io'],'Fail')
    def test_namespace_is_explicit_for_every_namespaced_object(self):
        for obj in self.objects:
            if obj['kind'] not in render.CLUSTER_KINDS:self.assertIn('namespace',obj['metadata'])

if __name__=='__main__':unittest.main()
