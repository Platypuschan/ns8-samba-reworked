# SPDX-License-Identifier: GPL-3.0-or-later

"""Upstream samba.py with this runner's address checks replaced.

The DC under test gets its address in the Podman test network, not on the
runner itself. IT_HOST_IPS lists the addresses that count as available on
the simulated node.
"""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "_upstream_samba", os.path.join(os.environ["IT_UPSTREAM_ROOT"], "imageroot/pypkg/samba.py"))
_upstream = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_upstream)


def _host_ips():
    return os.environ.get("IT_HOST_IPS", "").split()


def _isavailable(ipaddress):
    if ipaddress not in _host_ips():
        raise _upstream.IpNotAvailable(f"Address {ipaddress} is not on this test node")
    return True


def _hasfreeports(_ipaddress):
    return True


def _ipaddress_list(skip_wg0=False, only_wg0=False):
    return [{"ipaddress": address, "label": "it0"} for address in _host_ips()]


_upstream.ipaddress_check_isavailable = _isavailable
_upstream.ipaddress_check_hasfreeports = _hasfreeports
_upstream.ipaddress_list = _ipaddress_list
globals().update({name: value for name, value in vars(_upstream).items()
                  if not name.startswith("__")})
