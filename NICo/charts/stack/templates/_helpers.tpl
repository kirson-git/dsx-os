{{- define "nico.app" -}}
{{- $r := .root -}}
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .name }}
  namespace: argocd
  labels:
    dsx.nvidia.com/stack: nico
spec:
  project: default
  destination:
    server: https://kubernetes.default.svc
    namespace: {{ .namespace }}
  sources:
{{ toYaml .sources | indent 4 }}
  syncPolicy:
    automated:
      prune: false
      selfHeal: false
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - ClientSideApplyMigration=false
      - FailOnSharedResource=true
    retry:
      limit: 5
      backoff: {duration: 10s, factor: 2, maxDuration: 3m}
{{- end -}}
{{- define "nico.local" -}}
{{- $source := dict "repoURL" .root.Values.repoURL "targetRevision" .root.Values.revision "path" .path -}}
{{- if .values -}}{{- $_ := set $source "helm" (dict "releaseName" .release "valuesObject" .values) -}}{{- end -}}
{{ include "nico.app" (dict "root" .root "name" .name "namespace" .namespace "sources" (list $source)) }}
{{- end -}}
{{- define "nico.remote" -}}
{{- $r := .root -}}
{{- $h := dict "releaseName" .release "valuesObject" (.values | default dict) -}}
{{- if .valuesFile -}}{{- $_ := set $h "valueFiles" (list (printf "$settings/NICo/values/%s.yaml" .valuesFile)) -}}{{- end -}}
{{- $source := dict "repoURL" .repo "chart" .chart "targetRevision" .version "helm" $h -}}
{{- $refs := dict "repoURL" $r.Values.repoURL "targetRevision" $r.Values.revision "ref" "settings" -}}
{{ include "nico.app" (dict "root" $r "name" .name "namespace" .namespace "sources" (list $source $refs)) }}
{{- end -}}
