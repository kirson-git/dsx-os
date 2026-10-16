{{- define "dpf.reboot.pod" -}}
metadata:
  labels:
    app: dpf-host-reboot
spec:
  nodeName: {{ .host.managementNode | quote }}
  hostNetwork: true
  dnsPolicy: ClusterFirstWithHostNet
  serviceAccountName: dpf-reboot-{{ .host.name }}
  automountServiceAccountToken: {{ not .probe }}
  restartPolicy: Never
  activeDeadlineSeconds: 900
  containers:
  - name: reboot
    image: docker.io/nicolaka/netshoot@sha256:a20c2531bf35436ed3766cd6cfe89d352b050ccc4d7005ce6400adf97503da1b
    command: [python3, /scripts/host_reboot.py{{ if .probe }}, --probe{{ end }}]
    env:
    - {name: IDRAC_IP, value: {{ .host.idracIP | quote }}}
    - {name: EXPECTED_SERIAL, value: {{ .host.serial | quote }}}
    - {name: EXPECTED_DPUNODE, value: {{ .host.dpuNode | quote }}}
    - {name: VERIFY_TLS, value: {{ .host.verifyTLS | toString | quote }}}
    - name: REBOOT_JOB_UID
      valueFrom:
        fieldRef:
          fieldPath: metadata.labels['batch.kubernetes.io/controller-uid']
    securityContext:
      allowPrivilegeEscalation: false
      capabilities: {drop: [ALL]}
      readOnlyRootFilesystem: true
    resources:
      requests: {cpu: 10m, memory: 32Mi}
      limits: {memory: 128Mi}
    volumeMounts:
    - {name: scripts, mountPath: /scripts, readOnly: true}
    - {name: credentials, mountPath: /credentials, readOnly: true}
  volumes:
  - name: scripts
    configMap: {name: dpf-host-reboot-script}
  - name: credentials
    secret:
      secretName: dpf-host-reboot-credentials
      defaultMode: 256
  tolerations:
  - {key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}
{{- end -}}
