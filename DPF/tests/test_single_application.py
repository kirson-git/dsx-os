import pathlib
import sys
import unittest
import yaml
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import external
import render

class SingleApplicationTests(unittest.TestCase):
    def test_one_application_includes_platform_and_full_profile(self):
        cfg=yaml.safe_load((render.ROOT/'site.yaml').read_text())
        self.assertTrue(hasattr(external,'single_application'), 'One installation Application must be generated')
        app=external.single_application(cfg)
        self.assertNotIn('source',app['spec'])
        self.assertEqual([s['path'] for s in app['spec']['sources']],['DPF/generated/platform','DPF/profiles/two-tenant-hbn/desired'])
        self.assertTrue(app['spec']['sources'][1]['directory']['recurse'])
        self.assertFalse(app['spec']['syncPolicy']['automated']['prune'])
        self.assertNotIn('finalizers',app['metadata'])

    def test_profile_has_readiness_barriers_before_hardware(self):
        objects=[]
        for f in (render.ROOT/'profiles/two-tenant-hbn/desired').rglob('*.yaml'):
            objects.extend(o for o in yaml.safe_load_all(f.read_text()) if o)
        def wave(o):return int(o['metadata']['annotations']['argocd.argoproj.io/sync-wave'])
        jobs={o['metadata']['name']:o for o in objects if o['kind']=='Job'}
        self.assertIn('dpf-wait-operator',jobs)
        self.assertIn('dpf-wait-tenants',jobs)
        self.assertIn('dpf-check-bmc-secret',jobs)
        op=next(o for o in objects if o['kind']=='DPFOperatorConfig')
        tenants=[o for o in objects if o['kind']=='DPUCluster']
        hardware=[o for o in objects if o['kind'] in ('DPUSet','DPUDeployment','DPUDevice','DPUNode')]
        self.assertLess(wave(op),wave(jobs['dpf-wait-operator']))
        self.assertLess(wave(jobs['dpf-wait-operator']),min(map(wave,tenants)))
        self.assertLess(max(map(wave,tenants)),wave(jobs['dpf-wait-tenants']))
        self.assertLess(wave(jobs['dpf-wait-tenants']),wave(jobs['dpf-check-bmc-secret']))
        self.assertLess(wave(jobs['dpf-check-bmc-secret']),min(map(wave,hardware)))
        for job in jobs.values():self.assertEqual(job['metadata']['annotations']['argocd.argoproj.io/hook'],'Sync')
