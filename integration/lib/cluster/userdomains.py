# SPDX-License-Identifier: GPL-3.0-or-later

"""The test node has no user domains of its own."""


def get_external_domains(_rdb):
    return {}


def get_internal_domains(_rdb):
    return {}
