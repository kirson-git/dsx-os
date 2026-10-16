"""Tenant configuration must not leak into baseline or accept conflicting endpoints."""
import pathlib
import tempfile
import unittest
import yaml
import jsonschema
import test_package
render=test_package.render

class TenantTests(unittest.TestCase):
    def config(self):
        cfg=test_package.PackageTests().config()
        cfg['tenants']={'enabled':True,'items':[
            {'name':'europe','vip':'10.100.0.200','interface':'ens192','virtualRouterID':126,'maxNodes':1},
            {'name':'asia','vip':'10.100.0.201','interface':'ens192','virtualRouterID':127,'maxNodes':1}]}
        return cfg

    def test_enabled_tenants_require_operator_configuration(self):
        cfg=self.config();cfg['operator']['enabled']=False
        with self.assertRaises(ValueError):render.validate(cfg)

    def test_conflicting_or_invalid_endpoints_fail_before_render(self):
        for key,value in [('name','europe'),('vip','10.100.0.200'),('virtualRouterID',126),
                          ('virtualRouterID',0),('virtualRouterID',256),('virtualRouterID',True),
                          ('vip','CHANGE-ME'),('vip','192.0.2.10'),('vip','127.0.0.1'),
                          ('vip','2001:db8::1'),('interface',''),('interface','CHANGE-ME'),
                          ('interface','interface-is-too-long'),('name','../oops'),
                          ('name','x'*57),('maxNodes',0),('maxNodes',1001),('maxNodes',True)]:
            with self.subTest(key=key,value=value):
                cfg=self.config();cfg['tenants']['items'][1][key]=value
                with self.assertRaises(ValueError):render.validate(cfg)
        cfg=self.config();cfg['tenants']['items']=[]
        with self.assertRaises(ValueError):render.validate(cfg)
        cfg=self.config();cfg['tenants']['enabled']='false'
        with self.assertRaises(ValueError):render.validate(cfg)

    def test_real_render_creates_two_separate_control_planes_after_operator(self):
        cfg=self.config();render.validate(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            objects=render.render(cfg,pathlib.Path(tmp)/'rendered')
        clusters=[o for o in objects if o['kind']=='DPUCluster']
        self.assertEqual({o['metadata']['name'] for o in clusters},{'tenant-europe','tenant-asia'})
        schemas={o['spec']['names']['kind']:o['spec']['versions'][0]['schema']['openAPIV3Schema']
                 for o in objects if o['kind']=='CustomResourceDefinition'}
        config=next(o for o in objects if o['kind']=='DPFOperatorConfig')
        for obj in clusters:
            meta=obj['metadata'];namespace=meta['namespace']
            self.assertEqual(meta['name'],namespace)
            self.assertEqual(meta['labels']['customer.dpf.nvidia.com/tenant'],namespace.removeprefix('tenant-'))
            self.assertTrue(any(o['kind']=='Namespace' and o['metadata']['name']==namespace for o in objects))
            self.assertGreater(int(meta['annotations']['argocd.argoproj.io/sync-wave']),
                               int(config['metadata']['annotations']['argocd.argoproj.io/sync-wave']))
            jsonschema.Draft7Validator(schemas['DPUCluster']).validate(obj)
        self.assertFalse(any(o['kind'] in ('DPUSet','DPU','DPUDeployment','BFB') for o in objects))

    def test_disabled_examples_do_not_create_tenants(self):
        cfg=self.config();cfg['operator']['enabled']=False;cfg['tenants']['enabled']=False
        cfg['tenants']['items'][0]['vip']='CHANGE-ME'
        render.validate(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            objects=render.render(cfg,pathlib.Path(tmp)/'rendered')
        self.assertFalse(any(o['kind']=='DPUCluster' for o in objects))
        self.assertFalse(any(o['kind']=='Namespace' and o['metadata']['name'].startswith('tenant-') for o in objects))
