import pathlib
import sys
import tempfile
import unittest
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
import render
try:
    import external
except ImportError:
    external = None

class ExternalTests(unittest.TestCase):
    def test_renderer_exists(self):
        self.assertIsNotNone(external, 'External-Argo renderer is required')

    @unittest.skipIf(external is None, 'Renderer not implemented')
    def test_two_controllers_are_isolated(self):
        cfg=yaml.safe_load((render.ROOT/'site.yaml').read_text())
        ext,svc=external.argo_values(cfg)
        self.assertEqual(ext['configs']['params']['application.namespaces'],'argocd')
        self.assertEqual(svc['configs']['params']['application.namespaces'],'dpf-operator-system')
        self.assertNotEqual(ext['configs']['cm']['installationID'],svc['configs']['cm']['installationID'])
        self.assertFalse(svc['crds']['install'])
        cfg['externalArgo']['sameCluster']=False
        cfg['externalArgo']['destinationName']='dpf-management'
        self.assertTrue(external.argo_values(cfg)[1]['crds']['install'])
        cfg['externalArgo']['namespace']='dpf-operator-system'
        with self.assertRaises(ValueError):external.validate(cfg)

    @unittest.skipIf(external is None, 'Renderer not implemented')
    def test_platform_application_is_external_and_manual(self):
        cfg=yaml.safe_load((render.ROOT/'site.yaml').read_text())
        app=external.application(cfg,'dpf-platform','DPF/generated/platform')
        self.assertEqual(app['metadata']['namespace'],'argocd')
        self.assertEqual(app['spec']['destination'],{'name':'in-cluster','namespace':'dpf-operator-system'})
        self.assertNotIn('automated',app['spec']['syncPolicy'])
        self.assertNotIn('finalizers',app['metadata'])

    @unittest.skipIf(external is None, 'Renderer not implemented')
    def test_real_render_and_single_crd_owner(self):
        cfg=yaml.safe_load((render.ROOT/'site.yaml').read_text())
        for same in [True,False]:
            with self.subTest(same_cluster=same),tempfile.TemporaryDirectory() as tmp:
                cfg['externalArgo']['sameCluster']=same
                cfg['externalArgo']['destinationName']='in-cluster' if same else 'dpf-management'
                objects=external.generate(cfg,pathlib.Path(tmp)/'generated')
                entry=yaml.safe_load((pathlib.Path(tmp)/'install.yaml').read_text())
                self.assertEqual(entry['metadata']['name'],'dpf')
                self.assertEqual(entry['spec']['destination']['name'],cfg['externalArgo']['destinationName'])
                argo=[o for o in objects if o['kind']=='CustomResourceDefinition' and o['metadata']['name'].endswith('.argoproj.io')]
                self.assertEqual(len(argo),0 if same else 3)
                keys=[(o['apiVersion'],o['kind'],o['metadata'].get('namespace',''),o['metadata']['name']) for o in objects]
                self.assertEqual(len(keys),len(set(keys)))
                for obj in objects:
                    self.assertFalse(obj['kind']=='Secret' and (obj.get('data') or obj.get('stringData')))
                    self.assertNotIn('helm.sh/hook',obj['metadata'].get('annotations',{}))
                job=next(o for o in objects if o['kind']=='Job' and 'redis-secret-init' in o['metadata']['name'])
                self.assertEqual(job['metadata']['annotations']['argocd.argoproj.io/hook'],'Sync')
                self.assertLess(int(job['metadata']['annotations']['argocd.argoproj.io/sync-wave']),15)

if __name__=='__main__':unittest.main()
