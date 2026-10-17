"""Finds this laptop's addresses on the local network, for the setup QR."""
from __future__ import annotations

import socket


def lan_ipv4_addresses() -> list[str]:
    found: list[str] = []
    try:
        # No packet is sent: connecting a UDP socket just picks the outgoing interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ip.startswith("127.") and not ip.startswith("169.254.")]
