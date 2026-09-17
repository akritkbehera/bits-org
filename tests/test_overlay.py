# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import tempfile
import unittest
from unittest.mock import patch

from bits_helpers import overlay


class TestOverlayDispatch(unittest.TestCase):
    def test_lcg_is_a_builtin_format(self):
        self.assertIn("lcg", overlay._builtin_formats())

    def test_no_args_rc2(self):
        self.assertEqual(overlay.main([]), 2)

    def test_unknown_format_rc2(self):
        self.assertEqual(overlay.main(["nope"]), 2)

    def test_delegates_to_format_main(self):
        with patch("bits_helpers.overlay.lcg.main", return_value=0) as m:
            rc = overlay.main(["lcg", "-a", "x"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with(["-a", "x"])

    def test_external_plugin_via_env(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "myfmt.py"), "w") as fh:
                fh.write("def main(argv):\n    return 41 + len(argv)\n")
            self.assertNotIn("myfmt", overlay._builtin_formats())
            with patch.dict(os.environ, {"BITS_OVERLAY_PLUGINS": d}):
                self.assertEqual(overlay.main(["myfmt", "a"]), 42)


if __name__ == "__main__":
    unittest.main()
