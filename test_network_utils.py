import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import network_utils


class LocalIpTests(unittest.TestCase):
    def test_prefers_lan_address_over_docker_bridge(self):
        addresses = {
            "vEthernet (DockerNAT)": [
                SimpleNamespace(family=socket.AF_INET, address="172.18.0.1")
            ],
            "Wi-Fi": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.0.196")
            ],
        }
        stats = {
            "vEthernet (DockerNAT)": SimpleNamespace(isup=True),
            "Wi-Fi": SimpleNamespace(isup=True),
        }
        with patch.object(network_utils.psutil, "net_if_addrs", return_value=addresses), patch.object(
            network_utils.psutil, "net_if_stats", return_value=stats
        ):
            self.assertEqual(network_utils.get_local_ip(), "192.168.0.196")

    def test_uses_localhost_when_no_usable_interface_exists(self):
        addresses = {
            "Ethernet": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.0.196")
            ],
            "Loopback": [
                SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")
            ],
        }
        stats = {
            "Ethernet": SimpleNamespace(isup=False),
            "Loopback": SimpleNamespace(isup=True),
        }
        with patch.object(network_utils.psutil, "net_if_addrs", return_value=addresses), patch.object(
            network_utils.psutil, "net_if_stats", return_value=stats
        ):
            self.assertEqual(network_utils.get_local_ip(), "127.0.0.1")

    def test_prefers_physical_private_interface(self):
        addresses = {
            "Tailscale": [
                SimpleNamespace(family=socket.AF_INET, address="10.0.0.5")
            ],
            "Ethernet": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.0.196")
            ],
        }
        stats = {
            "Tailscale": SimpleNamespace(isup=True),
            "Ethernet": SimpleNamespace(isup=True),
        }
        with patch.object(network_utils.psutil, "net_if_addrs", return_value=addresses), patch.object(
            network_utils.psutil, "net_if_stats", return_value=stats
        ):
            self.assertEqual(network_utils.get_local_ip(), "192.168.0.196")


if __name__ == "__main__":
    unittest.main()
