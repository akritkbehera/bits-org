# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later
"""`view: true` — recipe flag that makes `bits enter/setenv <pkg>` auto-collapse
onto the merged view. The flag is parsed into the spec (build.py exports it as
BITS_MODULE_VIEW) and ModuleRecipe's GenerateModule emits `setenv BITS_VIEW 1`."""

import os
import subprocess
import unittest

from bits_helpers.recipe import parseRecipe

_RECIPE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_MODULE_RECIPE = os.path.join(_RECIPE_DIR, "bits-recipe-tools", "ModuleRecipe")


class TestViewFlagParse(unittest.TestCase):
    def test_view_true_lands_in_spec(self):
        recipe = "package: lcg-view\nversion: \"1\"\nview: true\n---\n"
        err, spec, _ = parseRecipe(lambda: recipe)
        self.assertIsNone(err)
        self.assertTrue(spec.get("view"))

    def test_no_view_flag_absent(self):
        err, spec, _ = parseRecipe(lambda: "package: x\nversion: \"1\"\n---\n")
        self.assertIsNone(err)
        self.assertFalse(spec.get("view"))


@unittest.skipUnless(os.path.isfile(_MODULE_RECIPE), "ModuleRecipe not present")
class TestGenerateModuleMarker(unittest.TestCase):
    def _gen(self, view_env):
        env = dict(os.environ, PKGNAME="lcg-view", PKGVERSION="LCG_110",
                   PKGREVISION="1", PKGHASH="abc", PKGDIR=".", PKGFAMILY="externals",
                   FULL_BUILD_REQUIRES="", BASEDIR="/tmp",
                   ARCHITECTURE="x86_64-el9-gcc14-opt", MODULEDIR="/tmp/mod",
                   INSTALLROOT="/tmp/ir")
        if view_env:
            env["BITS_MODULE_VIEW"] = "1"
        else:
            env.pop("BITS_MODULE_VIEW", None)
        out = subprocess.run(
            ["bash", "-c", ". '%s'; GenerateModule --none" % _MODULE_RECIPE],
            env=env, capture_output=True, text=True)
        return out.stdout

    def test_marker_emitted_with_flag(self):
        self.assertIn("setenv BITS_VIEW 1", self._gen(True))

    def test_marker_absent_without_flag(self):
        self.assertNotIn("BITS_VIEW", self._gen(False))


if __name__ == "__main__":
    unittest.main()
