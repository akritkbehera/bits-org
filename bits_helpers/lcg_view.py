# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later
"""DEPRECATED shim. The LCG overlay format moved to bits_helpers/overlay/lcg.py
(`bits overlay lcg`). This re-exports it so `bits lcg-view` and existing imports
keep working; prefer `from bits_helpers.overlay.lcg import ...`."""
from bits_helpers.overlay.lcg import (  # noqa: F401
    main, collect, resolve_dir, manifest_line, _build_view_and_setup,
)
