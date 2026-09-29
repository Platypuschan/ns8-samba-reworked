# SPDX-License-Identifier: GPL-3.0-or-later

"""File-backed stand-in for the NS8 agent library used by the actions."""

import os
import sys


def _environment_path():
    return os.path.join(os.environ["AGENT_STATE_DIR"], "environment")


def _read_environment():
    try:
        with open(_environment_path(), encoding="utf-8") as environment:
            return [line.rstrip("\n") for line in environment if line.strip()]
    except FileNotFoundError:
        return []


def _write_environment(lines):
    with open(_environment_path(), "w", encoding="utf-8") as environment:
        environment.write("".join(line + "\n" for line in lines))


def set_env(key, value):
    lines = [line for line in _read_environment() if not line.startswith(key + "=")]
    lines.append(f"{key}={value}")
    _write_environment(lines)


def unset_env(key):
    _write_environment([line for line in _read_environment() if not line.startswith(key + "=")])


def set_weight(*_args, **_kwargs):
    pass


def set_status(status):
    print(f"agent status: {status}", file=sys.stderr)


SD_ERR = "<3>"
SD_WARNING = "<4>"
SD_NOTICE = "<5>"


class _Redis:
    """Answers the reads of the restore steps; writes are accepted."""

    def get(self, key):
        if key == "cluster/network":
            return os.environ.get("IT_CLUSTER_NETWORK", "10.5.4.0/24")
        return None

    def hget(self, key, field):
        if key.endswith("/vpn") and field == "ip_address":
            return os.environ.get("IT_VPN_IP", "10.5.4.2")
        return None

    def sadd(self, *_args):
        return 1

    def srem(self, *_args):
        return 1

    def set(self, *_args):
        return True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def redis_connect(**_kwargs):
    return _Redis()
