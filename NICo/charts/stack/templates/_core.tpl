{{- define "nico.coreValues" -}}
{{- $v := .Values -}}
global:
  image:
    repository: {{ printf "%s/nvmetal-carbide" $v.images.registry | quote }}
    tag: {{ $v.images.tag | quote }}
  imagePullSecrets:
    - name: {{ $v.images.pullSecret }}
nico-api:
  hostname: {{ $v.site.apiHostname | quote }}
  webAuth:
    basic:
      existingSecret: {name: nico-api-web-basic-auth, key: password}
  rms: {enabled: false}
  componentManager: {enabled: false}
  dpf: {rbacCreate: true, operatorNamespace: dpf-operator-system}
  auth:
    additionalIssuerCns: [site-root]
  externalService:
    enabled: true
    annotations:
      metallb.universe.tf/loadBalancerIPs: {{ $v.network.apiVIP | quote }}
  certificate:
    extraDnsNames: [{{ $v.site.apiHostname | quote }}, carbide-api.forge, nico-api.forge]
  siteConfig:
    enabled: true
    nicoApiSiteConfig: |
      sitename = {{ $v.site.name | toJson }}
      initial_domain_name = {{ $v.site.domain | toJson }}
      dhcp_servers = {{ list $v.network.dhcpVIP | toJson }}
      route_servers = []
      enable_route_servers = false
      site_fabric_prefixes = {{ $v.network.fabricCIDRs | toJson }}
      deny_prefixes = {{ $v.network.denyCIDRs | toJson }}
      [pools.lo-ip]
      type = "ipv4"
      ranges = [{start = {{ $v.pools.loopback.start | quote }}, end = {{ $v.pools.loopback.end | quote }}}]
      [pools.vlan-id]
      type = "integer"
      ranges = [{start = {{ $v.pools.vlan.start | quote }}, end = {{ $v.pools.vlan.end | quote }}}]
      [pools.vni]
      type = "integer"
      ranges = [{start = {{ $v.pools.vni.start | quote }}, end = {{ $v.pools.vni.end | quote }}}]
      [pools.vpc-vni]
      type = "integer"
      ranges = [{start = {{ $v.pools.vpcVni.start | quote }}, end = {{ $v.pools.vpcVni.end | quote }}}]
      [dpf]
      enabled = {{ $v.dpf.enableIntegration }}
      docker_image_pull_secret = "nico-pull-secret"
{{ range $svc, $info := dict "dpu_agent" (list "nico-dpu-agent" "forge-dpu-agent") "dhcp_server" (list "nico-dhcp-server" "forge-dhcp-server") "fmds" (list "nico-fmds" "carbide-fmds") "otel" (list "nico-otelcol" "otelcol-contrib") }}
      [dpf.services.{{ $svc }}]
      helm_repo_url = {{ $v.images.dpuChartRepository | toJson }}
      helm_chart = {{ index $info 0 | quote }}
      helm_version = {{ $v.images.dpuChartVersion | quote }}
      docker_repo_url = {{ printf "%s/%s" $v.images.registry (index $info 1) | quote }}
      docker_image_tag = {{ $v.images.tag | quote }}
{{ end }}
nico-dsx-exchange-consumer: {enabled: false}
nico-dhcp:
  externalService:
    enabled: true
    annotations: {metallb.universe.tf/loadBalancerIPs: {{ $v.network.dhcpVIP | quote }}}
  config:
    kea:
      hookParameters:
        nameservers: {{ $v.network.resolverVIP | quote }}
        ntpServer: {{ join "," $v.network.ntpVIPs | quote }}
        provisioningServer: {{ $v.network.pxeVIP | quote }}
nico-pxe:
  externalService:
    enabled: true
    annotations: {metallb.universe.tf/loadBalancerIPs: {{ $v.network.pxeVIP | quote }}}
  certificate:
    extraDnsNames: [carbide-pxe.forge, nico-pxe.forge, carbide-static-pxe.forge]
  bootArtifactContainers:
    - name: boot-artifacts-x86-64
      image: {{ printf "%s/boot-artifacts-x86_64:%s" $v.images.registry $v.images.tag | quote }}
      command: [sh, -c, "cp -r /x86_64 /forge-boot-artifacts/blobs/internal"]
    - name: boot-artifacts-aarch64
      image: {{ printf "%s/boot-artifacts-aarch64:%s" $v.images.registry $v.images.tag | quote }}
      command: [sh, -c, "cp -r /aarch64 /apt /forge-boot-artifacts/blobs/internal"]
nico-ssh-console-rs:
  externalService:
    enabled: true
    annotations: {metallb.universe.tf/loadBalancerIPs: {{ $v.network.consoleVIP | quote }}}
nico-dns:
  replicas: {{ len $v.network.dnsVIPs }}
  externalService:
    enabled: true
    perPodAnnotations:
{{ range $v.network.dnsVIPs }}
      - metallb.universe.tf/loadBalancerIPs: {{ . | quote }}
{{ end }}
nico-ntp:
  replicas: {{ len $v.network.ntpVIPs }}
  ntp:
    upstreamServers: {{ $v.network.upstreamNTP | toJson }}
  externalService:
    enabled: true
    perPodAnnotations:
{{ range $v.network.ntpVIPs }}
      - metallb.universe.tf/loadBalancerIPs: {{ . | quote }}
{{ end }}
unbound:
  enabled: true
  image: {repository: {{ $v.images.unboundRepository | quote }}, tag: {{ $v.images.unboundTag | quote }}}
  exporterImage: {repository: {{ $v.images.unboundExporterRepository | quote }}, tag: {{ $v.images.unboundExporterTag | quote }}}
  externalService:
    enabled: true
    annotations: {metallb.universe.tf/loadBalancerIPs: {{ $v.network.resolverVIP | quote }}}
  localConfig:
    forwarders.conf: |
      forward-zone:
          name: .
{{ range $v.network.upstreamDNS }}
          forward-addr: {{ . }}
{{ end }}
  localData:
{{ range $name, $addresses := dict "carbide-api.forge" (list $v.network.apiVIP) "nico-api.forge" (list $v.network.apiVIP) "carbide-pxe.forge" (list $v.network.pxeVIP) "nico-pxe.forge" (list $v.network.pxeVIP) "carbide-static-pxe.forge" (list $v.network.pxeVIP) "carbide-ntp.forge" $v.network.ntpVIPs "nico-ntp.forge" $v.network.ntpVIPs "unbound.forge" (list $v.network.resolverVIP) }}
    - name: {{ $name }}
      addresses: {{ $addresses | toJson }}
{{ end }}
{{- end -}}
