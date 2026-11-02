"""Helpers for selecting a LAN address to display in application links."""

import ipaddress
import logging
import socket

import psutil


logger = logging.getLogger(__name__)

_VIRTUAL_INTERFACE_MARKERS = (
    "virtual",
    "vmware",
    "virtualbox",
    "vbox",
    "hyper-v",
    "hyperv",
    "vethernet",
    "docker",
    "wsl",
    "loopback",
    "vpn",
    "bridge",
    "zerotier",
    "tailscale",
    "hamachi",
    "wireguard",
)


def _address_priority(address, virtual_interface):
    if address.version == 4 and address.is_private:
        if address in ipaddress.ip_network("192.168.0.0/16"):
            network_priority = 0
        elif address in ipaddress.ip_network("10.0.0.0/8"):
            network_priority = 1
        else:
            network_priority = 2
    else:
        network_priority = 3
    return virtual_interface, network_priority, int(address)


def get_local_ip():
    """Return a usable LAN IPv4 address, preferring physical private networks."""
    try:
        addresses = psutil.net_if_addrs()
        interface_stats = psutil.net_if_stats()
    except (OSError, psutil.Error):
        logger.exception("Не удалось получить список сетевых интерфейсов")
        return "127.0.0.1"

    candidates = []
    for interface, interface_addresses in addresses.items():
        stats = interface_stats.get(interface)
        if stats is not None and not stats.isup:
            continue
        normalized_name = interface.lower().replace(" ", "")
        virtual_interface = any(
            marker in normalized_name for marker in _VIRTUAL_INTERFACE_MARKERS
        )
        for entry in interface_addresses:
            if entry.family != socket.AF_INET:
                continue
            try:
                address = ipaddress.ip_address(entry.address)
            except ValueError:
                continue
            if (
                address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_unspecified
            ):
                continue
            candidates.append(
                (_address_priority(address, virtual_interface), str(address))
            )

    if not candidates:
        logger.warning("Не найден активный сетевой IPv4-адрес; используется localhost")
        return "127.0.0.1"

    candidates.sort(key=lambda candidate: candidate[0])
    return candidates[0][1]
