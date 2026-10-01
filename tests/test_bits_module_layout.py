"""Exercise the shell frontend against flat and category install layouts."""

import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from bits_helpers import cvmfs_catalog

BITS = str(Path(__file__).resolve().parents[1] / "bits")


@unittest.skipUnless(shutil.which("modulecmd"), "Environment Modules required")
class ModuleLayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.arch = "el9_amd64_gcc14"
        self.root = self.work / self.arch
        self.env = dict(os.environ, HOME=str(self.work), MODULES_SHELL="bash",
                        BITS_WORK_DIR=str(self.work), BITS_PKG_PREFIX="")
        for key in ("LOADEDMODULES", "_LMFILES_", "MODULEPATH", "BITSLVL"):
            self.env.pop(key, None)

    def module(self, relative):
        prefix = self.root / relative
        pkg = prefix.parent.name
        path = prefix / "etc/modulefiles" / pkg
        path.parent.mkdir(parents=True)
        path.write_text('#%Module1.0\nmodule load BASE/1.0\n'
                        'setenv TEST_ROOT "$::env(BASEDIR)/' + relative + '"\n')
        return prefix

    def run_bits(self, *args):
        return subprocess.run(["bash", BITS, *args], cwd=self.work, env=self.env,
                              text=True, capture_output=True, check=True).stdout

    def test_query_mixed_layout_and_aliases_without_module_cache(self):
        self.module("Flat/1")
        self.module("external/Tool/2")
        self.module("lcg/ROOT/3")
        self.module("cms/App/4")
        (self.root / "external/Tool/latest").symlink_to("2")
        self.assertEqual(self.run_bits("q").splitlines(),
                         ["App/4", "Flat/1", "ROOT/3", "Tool/2", "Tool/latest"])
        self.assertFalse((self.work / "MODULES").exists())

    def test_load_setenv_and_cache_refresh(self):
        prefix = self.module("external/Tool/2")
        output = self.run_bits("load", "Tool/2")
        self.assertIn(str(prefix), output)
        self.assertEqual(self.run_bits("setenv", "Tool/2", "-c", "sh", "-c",
                                       'printf "%s" "$TEST_ROOT"'), str(prefix))
        cache = self.work / "MODULES" / self.arch
        self.assertTrue((cache / "Tool/2").is_file())
        # Changes below the category must invalidate a previously synced cache.
        self.module("external/Tool/3")
        stamp = cache / ".bits_sync_stamp_v2"
        os.utime(stamp, (1, 1))
        self.assertIn(str(self.root / "external/Tool/3"),
                      self.run_bits("load", "Tool/3"))
        self.assertTrue((cache / "Tool/2").is_file())
        shutil.rmtree(prefix)
        os.utime(stamp, (1, 1))
        self.run_bits("load", "Tool/3")
        self.assertFalse((cache / "Tool/2").exists())


class CatalogPackageLayoutTest(unittest.TestCase):
    def test_category_and_flat_candidates_include_symlinks(self):
        entries = [("Flat/1", cvmfs_catalog.kFlagDir),
                   ("external/Tool/2", cvmfs_catalog.kFlagDir),
                   ("external/Tool/latest", cvmfs_catalog.kFlagLink),
                   ("external/Tool/2/lib", cvmfs_catalog.kFlagDir)]
        with tempfile.TemporaryDirectory() as root, \
             patch.object(cvmfs_catalog, "list_entries", return_value=(entries, {})), \
             redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cvmfs_catalog.main([root, "--package-dirs"]), 0)
            self.assertEqual(out.getvalue().splitlines(),
                             [root + "/" + p for p, _ in entries[:3]])
