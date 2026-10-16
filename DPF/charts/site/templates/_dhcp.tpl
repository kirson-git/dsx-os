{{- define "dpf.ipNumber" -}}
{{- $o := splitList "." . -}}
{{- add (mul (int (index $o 0)) 16777216) (mul (int (index $o 1)) 65536) (mul (int (index $o 2)) 256) (int (index $o 3)) -}}
{{- end -}}

{{- define "dpf.dhcpConfig" -}}
{{- $d := .Values.dhcp -}}
{{- $base := include "dpf.ipNumber" $d.subnet | int64 -}}
{{- $size := sub 4294967296 (include "dpf.ipNumber" $d.netmask | int64) -}}
{{- if ne (mod $base $size) (int64 0) -}}
{{- fail "dhcp.subnet must be the network address for dhcp.netmask" -}}
{{- end -}}
{{- $last := sub (add $base $size) 1 -}}
{{- $seenMAC := dict -}}
{{- $seenIP := dict -}}
{{- $seenName := dict -}}
{{- range $address := list $d.serverIP $d.gateway -}}
{{- $n := include "dpf.ipNumber" $address | int64 -}}
{{- if or (le $n $base) (ge $n $last) -}}
{{- fail "DHCP serverIP and gateway must be usable addresses in dhcp.subnet/netmask" -}}
{{- end -}}
{{- if has $address (list $.Values.europeVIP $.Values.asiaVIP $.Values.apiServerIP) -}}
{{- fail "DHCP serverIP/gateway must not overlap Kubernetes API addresses" -}}
{{- end -}}
{{- end -}}
{{- if eq $d.serverIP $d.gateway -}}{{ fail "DHCP serverIP and gateway must differ" }}{{- end -}}
{{- range $r := $d.reservations -}}
{{- $n := include "dpf.ipNumber" $r.ip | int64 -}}
{{- $mac := lower $r.mac -}}
{{- if empty $mac -}}{{ fail (printf "Fill in the MAC for %s before enabling DHCP" $r.name) }}{{- end -}}
{{- if or (le $n $base) (ge $n $last) (has $r.ip (list $d.serverIP $d.gateway $.Values.europeVIP $.Values.asiaVIP $.Values.apiServerIP)) -}}
{{- fail (printf "Reservation %s needs a usable subnet address distinct from server, gateway and VIPs" $r.name) -}}
{{- end -}}
{{- if or (eq $mac "00:00:00:00:00:00") (regexMatch "^[0-9a-f][13579bdf]:" $mac) -}}
{{- fail (printf "Reservation %s needs a unicast MAC" $r.name) -}}
{{- end -}}
{{- if or (hasKey $seenMAC $mac) (hasKey $seenIP $r.ip) (hasKey $seenName $r.name) -}}
{{- fail "DHCP reservation names, MACs and IPs must be unique" -}}
{{- end -}}
{{- $_ := set $seenMAC $mac true -}}{{- $_ := set $seenIP $r.ip true -}}{{- $_ := set $seenName $r.name true -}}
{{- end -}}
port=0
interface={{ $d.interface }}
except-interface=lo
bind-interfaces
user=root
group=root
dhcp-range={{ $d.subnet }},static,{{ $d.netmask }},30m
dhcp-ignore=tag:!known
dhcp-option=option:router,{{ $d.gateway }}
dhcp-option=option:dns-server{{ range $ip := $d.dnsServers }},{{ $ip }}{{ end }}
dhcp-leasefile=/run/dhcp/leases
pid-file=/run/dhcp/dnsmasq.pid
log-facility=-
log-dhcp
{{ range $r := $d.reservations -}}
dhcp-host={{ lower $r.mac }},id:*,set:{{ $r.name }},{{ $r.ip }},30m
{{ if and (hasKey $r "gateway") (not $r.gateway) -}}
dhcp-option=tag:{{ $r.name }},option:router
{{ end -}}
{{ if $r.netmask -}}
dhcp-option=tag:{{ $r.name }},option:netmask,{{ $r.netmask }}
{{ end -}}
{{ end -}}
{{- end -}}
