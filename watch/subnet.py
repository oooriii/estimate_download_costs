from __future__ import annotations

import ipaddress


def subnet_key(remote_host: str, *, mask_v4: int = 24, mask_v6: int = 48) -> str | None:
    if remote_host in ("-", ""):
        return None
    try:
        address = ipaddress.ip_address(remote_host)
    except ValueError:
        return None
    if address.version == 4:
        network = ipaddress.ip_network(f"{address}/{mask_v4}", strict=False)
    else:
        network = ipaddress.ip_network(f"{address}/{mask_v6}", strict=False)
    return str(network)


def collapse_subnets(cidr_keys: list[str]) -> list[str]:
    """Merge adjacent/overlapping CIDR blocks where possible."""
    networks: list[ipaddress._BaseNetwork] = []
    for key in cidr_keys:
        try:
            networks.append(ipaddress.ip_network(key, strict=False))
        except ValueError:
            continue
    if not networks:
        return []
    collapsed = list(ipaddress.collapse_addresses(networks))
    return [
        str(network)
        for network in sorted(
            collapsed,
            key=lambda n: (n.version, n.network_address),
        )
    ]


def collapse_host_ips(ips: list[str]) -> list[str]:
    """Collapse many host IPs into fewer CIDRs (fast path for large lists)."""
    unique = sorted({ip for ip in ips if ip}, key=lambda value: ipaddress.ip_address(value))
    if not unique:
        return []

    if len(unique) <= 2048:
        return collapse_subnets(unique)

    by_prefix: dict[str, list[int]] = {}
    for ip in unique:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if address.version != 4:
            return collapse_subnets(unique)
        octets = str(address).split(".")
        prefix = ".".join(octets[:3])
        by_prefix.setdefault(prefix, []).append(int(octets[3]))

    merged: list[ipaddress._BaseNetwork] = []
    for prefix, host_octets in by_prefix.items():
        host_octets = sorted(set(host_octets))
        if len(host_octets) == 256:
            merged.append(ipaddress.ip_network(f"{prefix}.0/24", strict=False))
            continue
        networks = [
            ipaddress.ip_network(f"{prefix}.{host}/32", strict=False)
            for host in host_octets
        ]
        merged.extend(ipaddress.collapse_addresses(networks))

    collapsed = list(ipaddress.collapse_addresses(merged))
    return [
        str(network)
        for network in sorted(
            collapsed,
            key=lambda n: (n.version, n.network_address),
        )
    ]
