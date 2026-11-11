"""Data validation and inventory assessment for the Bash preparation helper."""
import ipaddress
import json
import os
from pathlib import Path
import re
import sys


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("settings must be an object")
    required = {"schema_version", "dpf_version", "mode", "context", "node_interface",
                "management_cidr", "bmc_ips", "bmc_user", "dpu_api_vip", "vip_mode",
                "dhcp", "storage_class", "registry"}
    if set(data) != required:
        raise ValueError("settings fields differ from the example (missing or unknown keys)")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    if data["dpf_version"] != "v26.4.0" or data["mode"] != "zero-trust":
        raise ValueError("this helper supports v26.4.0 / zero-trust only")
    for key in required - {"schema_version", "bmc_ips"}:
        value = data[key]
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError(f"{key} must be a nonempty single-line string")
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", data["node_interface"]):
        raise ValueError("invalid node_interface")
    if "/" not in data["management_cidr"]:
        raise ValueError("management_cidr needs a prefix length")
    ipaddress.IPv4Network(data["management_cidr"], strict=True)
    addresses = data["bmc_ips"]
    if not isinstance(addresses, list) or not addresses or not all(isinstance(x, str) for x in addresses):
        raise ValueError("bmc_ips must be a nonempty list of IPv4 strings")
    if len(addresses) != len(set(addresses)):
        raise ValueError("duplicate BMC addresses")
    for value in [*addresses, data["dpu_api_vip"]]:
        address = ipaddress.IPv4Address(value)
        if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_link_local or str(address) == "255.255.255.255":
            raise ValueError("use routable unicast IPv4 addresses")
    if data["dpu_api_vip"] in addresses:
        raise ValueError("DPU API VIP cannot equal a BMC address")
    for key, allowed in {"vip_mode": {"keepalived", "existing", "metallb-l2", "metallb-bgp", "undecided"},
                         "dhcp": {"external", "temporary", "missing"}}.items():
        if data[key] not in allowed:
            raise ValueError(f"invalid {key}; choose {', '.join(sorted(allowed))}")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", data["storage_class"]):
        raise ValueError("invalid storage_class")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]*", data["registry"]) or "://" in data["registry"]:
        raise ValueError("registry must be upstream or a hostname/project without scheme or credentials")
    return data


def report(directory, config):
    root = Path(directory)
    failures = []

    def emit(level, message):
        print(f"{level}: {message}")
        if level == "FAIL":
            failures.append(message)

    def read(name, kind):
        try:
            if (root / f"{name}.stderr").exists():
                raise ValueError("command failed; inspect its .stderr file")
            result = json.loads((root / f"{name}.json").read_text())
            if not isinstance(result, kind):
                raise ValueError("unexpected response shape")
            return result
        except (OSError, ValueError) as error:
            emit("FAIL", f"Unable to assess {name}: {error}")
            return None

    print("DPF v26.4.0 — read-only preparation inventory")
    version = read("version", dict)
    if version is not None:
        value = version.get("serverVersion", {}).get("gitVersion", "unknown")
        match = re.fullmatch(r"v1\.(\d+)\.\d+(?:[+-].+)?", value)
        supported = bool(match and 33 <= int(match[1]) <= 36)
        emit("PASS" if supported else "FAIL", f"Kubernetes {value}; documented supported range 1.33–1.36")
    nodes = read("nodes", dict)
    if nodes is not None:
        if not nodes.get("items"):
            emit("FAIL", "No nodes returned")
        for node in nodes.get("items", []):
            status = node.get("status", {})
            name = node["metadata"]["name"]
            ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions", []))
            emit("PASS" if ready else "FAIL", f"{name}: Ready={ready}; allocatable={json.dumps(status.get('allocatable', {}), sort_keys=True)}")
            for condition in status.get("conditions", []):
                if condition.get("type") in {"MemoryPressure", "DiskPressure", "PIDPressure"} and condition.get("status") == "True":
                    emit("FAIL", f"{name}: {condition['type']}")
    storage = read("storage", dict)
    if storage is not None:
        names = [s["metadata"]["name"] for s in storage.get("items", [])]
        emit("INFO", "StorageClasses: " + (", ".join(names) or "none"))
        if config and config["storage_class"] not in names:
            emit("FAIL", "Selected existing StorageClass was not found")
    deployments = read("deployments", dict)
    if deployments is not None:
        for deployment in deployments.get("items", []):
            for container in deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
                image = container.get("image", "")
                if "local-path-provisioner" in image:
                    emit("INFO" if image.endswith(":v0.0.34") else "WARN",
                         f"Existing storage image {image}; upstream default v0.0.34. Review reuse; do not install a duplicate.")
    releases = read("releases", list)
    if releases is not None:
        emit("INFO", f"Helm releases returned: {len(releases)}")
        if releases:
            emit("WARN", "Existing releases require review for prerequisite ownership; inspect releases.json")
        if len(releases) >= 1000:
            emit("WARN", "Helm inventory reached its 1000-release limit and may be incomplete")
    if not config:
        emit("WARN", "No questionnaire settings supplied; this is cluster inventory only")
    else:
        if config["dhcp"] != "external":
            emit("WARN", f"DHCP is {config['dhcp']}; establish enduring management addressing before provisioning")
        if config["vip_mode"] == "undecided":
            emit("WARN", "VIP delivery is undecided")
    emit("UNTESTED", "BMC credentials, node OOB interface, DHCP availability, VIP reservation/routing, DNS/NTP, image/BFB downloads, hardware compatibility and workload resource headroom")
    emit("INFO", "No cluster changes made. This report is not an installation readiness certificate.")
    return 1 if failures else 0


def main():
    action = sys.argv[1]
    try:
        if action == "save":
            data = validate(json.load(sys.stdin))
            target = Path(sys.argv[2])
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
            print(f"Settings saved: {target}")
        elif action == "validate":
            validate(json.loads(Path(sys.argv[2]).read_text()))
            print("Settings valid (network reachability and credentials not tested).")
        elif action == "report":
            config = validate(json.loads(Path(sys.argv[3]).read_text())) if len(sys.argv) > 3 and sys.argv[3] else None
            return report(sys.argv[2], config)
        else:
            raise ValueError("unknown action")
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"Invalid settings or unreadable input: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
