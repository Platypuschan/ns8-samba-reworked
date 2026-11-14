# SPDX-License-Identifier: GPL-3.0-or-later
"""The ntfy token of the AD replication monitor, kept in a private file.

The module environment (Redis, the environment file, every backup of it) is
readable by more than the monitor, so the token lives in a 0600 file in the
module state instead. The file is part of the backup (etc/state-include.conf).
"""
import os
from pathlib import Path

NAME = "ntfy-replication-token"


def path():
    return Path(os.environ["AGENT_STATE_DIR"]) / NAME


def read():
    try:
        return path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def write(token):
    """Atomically store the token, readable by the module user only."""
    if not token or any(char in token for char in "\r\n"):
        raise ValueError("invalid token")
    target = path()
    temporary = target.with_name(NAME + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if read() != token:
        raise OSError("the stored token does not read back")


def clear():
    path().unlink(missing_ok=True)
