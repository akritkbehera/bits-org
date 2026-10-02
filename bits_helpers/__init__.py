# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

# This file is needed to package build_template.sh.

# Single-source the version: git describe in a source checkout, else the
# setuptools_scm version of an installed package (see version.py).
from bits_helpers.version import version_info as _version_info

_VERSION_INFO = _version_info()
__version__ = _VERSION_INFO["version"] if _VERSION_INFO else None
del _version_info
