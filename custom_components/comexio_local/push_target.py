"""Shared validation for COMEXIO-to-Home-Assistant local push destinations."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def private_lan_host_port(url: str) -> str | None:
    """Return IPv4 host:port only for a private, routable HTTP callback base.

    A COMEXIO device connects to this address itself; loopback, wildcard,
    multicast, link-local, public IPs and URLs with credentials/paths are unsafe.
    """
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or not parsed.hostname or parsed.port is None
                or parsed.port == 0 or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            return None
        address = ipaddress.ip_address(parsed.hostname)
        if (not isinstance(address, ipaddress.IPv4Address)
                or not address.is_private or address.is_loopback
                or address.is_link_local or address.is_multicast
                or address.is_unspecified or address.is_reserved):
            return None
        return f'{address}:{parsed.port}'
    except (TypeError, ValueError):
        return None
