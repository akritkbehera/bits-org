# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later
import json
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


class TestLcgCollect(unittest.TestCase):
    def _meta(self, d, name, family=""):
        os.makedirs(d)
        with open(os.path.join(d, ".meta.json"), "w") as fh:
            json.dump({"package": {"name": name, "version": "1", "pkg_family": family}}, fh)

    def test_family_packages_are_found(self):
        from bits_helpers.overlay.lcg import collect
        with tempfile.TemporaryDirectory() as wd:
            a = os.path.join(wd, "x86_64-el9-gcc14-opt")
            self._meta(os.path.join(a, "ROOT", "1-1"), "ROOT")
            self._meta(os.path.join(a, "MCGenerators", "evtgen", "1-1"), "evtgen", "MCGenerators")
            # A .meta.json inside a package's own tree is not a package,
            # even when it is not valid JSON; nor is a <pkg>/latest link.
            self._meta(os.path.join(a, "ROOT", "1-1", "etc"), "stray")
            os.makedirs(os.path.join(a, "ROOT", "1-1", "share"))
            with open(os.path.join(a, "ROOT", "1-1", "share", ".meta.json"), "w") as fh:
                fh.write("[")
            os.symlink("1-1", os.path.join(a, "ROOT", "latest"))
            records, warnings, errors = collect(wd, "x86_64-el9-gcc14-opt")
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual(sorted(records), ["ROOT", "evtgen"])
        self.assertTrue(records["evtgen"][0].endswith("MCGenerators/evtgen/1-1"))


if __name__ == "__main__":
    unittest.main()
