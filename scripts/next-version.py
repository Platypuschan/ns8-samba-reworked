#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

import re
import sys


if len(sys.argv) != 2:
    raise SystemExit(f"usage: {sys.argv[0]} MAJOR.MINOR.PATCH")

match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", sys.argv[1])
if not match:
    raise SystemExit(f"invalid semantic version: {sys.argv[1]}")

major, minor, _patch = (int(value) for value in match.groups())
print(f"{major}.{minor + 1}.0")
