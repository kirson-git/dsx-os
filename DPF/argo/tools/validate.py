#!/usr/bin/env python3
"""Validate generated YAML locally. Requires PyYAML and jsonschema; no cluster access."""
import argparse
import json
import pathlib
import yaml
import jsonschema

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('manifest',type=pathlib.Path)
parser.add_argument('--kubernetes-schema',type=pathlib.Path,required=True,
                    help='Official Kubernetes api/openapi-spec/swagger.json matching the target version')
args=parser.parse_args()
schema=json.loads(args.kubernetes_schema.read_text())
# Kubernetes IntOrString is encoded as format in its OpenAPI v2 schema.
for definition in schema['definitions'].values():
    if definition.get('format')=='int-or-string':definition['type']=['integer','string']
lookup={}
for definition in schema['definitions'].values():
    for gvk in definition.get('x-kubernetes-group-version-kind',[]):
        api=(gvk['group']+'/' if gvk['group'] else '')+gvk['version']
        lookup[(api,gvk['kind'])]=definition
objects=[o for o in yaml.safe_load_all(args.manifest.read_text()) if o]
for obj in objects:
    if obj['kind']=='CustomResourceDefinition':
        for version in obj['spec']['versions']:
            lookup[(obj['spec']['group']+'/'+version['name'],obj['spec']['names']['kind'])]=version['schema']['openAPIV3Schema']

def omit_nulls(value):
    # Typed Kubernetes fields accept omitted optional values; Helm emits null for many.
    if isinstance(value,dict):return {k:omit_nulls(v) for k,v in value.items() if v is not None}
    if isinstance(value,list):return [omit_nulls(v) for v in value]
    return value

resolver=jsonschema.RefResolver.from_schema(schema)
for obj in objects:
    key=(obj['apiVersion'],obj['kind'])
    if key not in lookup:raise ValueError(f'No schema for {key}')
    jsonschema.Draft7Validator(lookup[key],resolver=resolver).validate(omit_nulls(obj))
print(f'PASS: {len(objects)} resources checked against Kubernetes OpenAPI and bundled CRD schemas.')
print('Check normalizes optional null fields and Kubernetes IntOrString; admission/CEL/runtime behavior is not exercised.')
