# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for bits_helpers/provenance.py (build_id / abi_tag) and the additive
provenance fields in create_provenance_info().

Doubles as the ADR-0001 Stage-0 backward-compatibility guard: the new fields
must be *added* to .meta.json, never replace or drop the pre-existing keys, and
the helpers must never raise on minimal input.
"""

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from bits_helpers import provenance as pv
from bits_helpers.build import create_provenance_info


def _spec(name, **kw):
    base = {
        "package": name, "version": "1.0", "revision": "1", "hash": "h" + name,
        "tag": None, "source": None, "requires": [],
        "build_requires": [], "runtime_requires": [],
        "full_build_requires": [], "full_runtime_requires": [],
    }
    base.update(kw)
    return base


class TestProvenanceHelpers(unittest.TestCase):

    def test_build_id_deterministic(self):
        specs = {"a": _spec("a"), "b": _spec("b")}
        args = SimpleNamespace(defaults=["release", "gcc15"],
                               architecture="ubuntu2510_x86-64-gcc15-dbg")
        self.assertEqual(pv.compute_build_id(specs, args),
                         pv.compute_build_id(dict(specs), args))

    def test_build_id_sensitive_to_member_hash(self):
        args = SimpleNamespace(defaults=["release"], architecture="x")
        self.assertNotEqual(
            pv.compute_build_id({"a": _spec("a", hash="h1")}, args),
            pv.compute_build_id({"a": _spec("a", hash="h2")}, args))

    def test_build_id_has_readable_label(self):
        args = SimpleNamespace(defaults=["release", "gcc15"], architecture="x")
        self.assertTrue(
            pv.compute_build_id({"a": _spec("a")}, args).startswith("release_gcc15-"))

    def test_build_id_minimal_does_not_crash(self):
        args = SimpleNamespace(defaults=[], architecture="")
        self.assertTrue(pv.compute_build_id({}, args).startswith("local-"))
        # specs lacking a hash are excluded, not fatal
        self.assertTrue(pv.compute_build_id({"x": {"package": "x"}}, args))

    def test_abi_tag_from_arch(self):
        args = SimpleNamespace(architecture="ubuntu2510_x86-64-gcc15-dbg")
        self.assertEqual(pv.compute_abi_tag(args), "ubuntu2510_x86-64-gcc15-dbg")

    def test_abi_tag_appends_cxxstd(self):
        args = SimpleNamespace(architecture="arch")
        os.environ["CXXSTD"] = "23"
        try:
            self.assertEqual(pv.compute_abi_tag(args), "arch+c++23")
        finally:
            os.environ.pop("CXXSTD", None)

    def test_abi_tag_empty_env(self):
        self.assertEqual(pv.compute_abi_tag(SimpleNamespace(architecture="")), "")

    def test_recipe_tools_ref(self):
        self.assertEqual(pv.recipe_tools_ref({}), "")
        self.assertEqual(
            pv.recipe_tools_ref({"bits-recipe-tools": {"version": "0.0.28",
                                                       "hash": "abcdef1234"}}),
            "0.0.28-abcdef12")


class TestProvenanceRecord(unittest.TestCase):
    """create_provenance_info(): new keys are additive, old keys preserved."""

    OLD_KEYS = ("comment", "bits_version", "dist", "architecture",
                "defaults", "package", "dependencies")
    NEW_KEYS = ("build_id", "abi_tag", "reuse_policy", "provenance", "repro",
                "cvmfs_layout")

    def _record(self, args):
        specs = {"a": _spec("a")}
        os.environ["BITS_DIST_HASH"] = "deadbeef"
        try:
            return json.loads(create_provenance_info("a", specs, args))
        finally:
            os.environ.pop("BITS_DIST_HASH", None)

    def test_old_keys_preserved_new_keys_added(self):
        rec = self._record(SimpleNamespace(annotate={}, architecture="arch",
                                           defaults=["release"], reusePolicy="strict"))
        for k in self.OLD_KEYS:
            self.assertIn(k, rec, "pre-existing key %r dropped" % k)
        for k in self.NEW_KEYS:
            self.assertIn(k, rec, "new key %r missing" % k)
        self.assertEqual(rec["reuse_policy"], "strict")
        self.assertEqual(rec["provenance"], "pure")
        self.assertEqual(rec["package"]["hash"], "ha")
        self.assertIsNone(rec["cvmfs_layout"])   # None when args has no layout

    def test_cvmfs_layout_recorded_when_present(self):
        layout = {"cvmfs_dir": "/cvmfs/x", "install_dir": "arch",
                  "module_dir": "arch/modules", "views_dir": "Views",
                  "install_path": "/cvmfs/x/arch", "module_path": "/cvmfs/x/arch/modules",
                  "views_path": "/cvmfs/x/Views"}
        rec = self._record(SimpleNamespace(annotate={}, architecture="arch",
                                           defaults=["release"], cvmfsLayout=layout))
        self.assertEqual(rec["cvmfs_layout"]["views_dir"], "Views")
        self.assertEqual(rec["cvmfs_layout"]["views_path"], "/cvmfs/x/Views")

    def test_reuse_policy_defaults_to_strict_when_arg_absent(self):
        # args without a reuse_policy attribute (the aliBuild simple case)
        rec = self._record(SimpleNamespace(annotate={}, architecture="arch",
                                           defaults=["release"]))
        self.assertEqual(rec["reuse_policy"], "strict")

    def _record_specs(self, specs):
        args = SimpleNamespace(annotate={}, architecture="arch", defaults=["release"])
        os.environ["BITS_DIST_HASH"] = "x"
        try:
            return json.loads(create_provenance_info("a", specs, args))
        finally:
            os.environ.pop("BITS_DIST_HASH", None)

    def test_provenance_pure_when_closure_is_clean(self):
        # No untracked_requires anywhere in the closure -> pure. (The legacy
        # cvmfs:// graft that also produced "loose" was removed in Step 5.)
        specs = {
            "a": _spec("a", full_runtime_requires=["dep"], full_build_requires=[]),
            "dep": _spec("dep"),   # locally built
        }
        self.assertEqual(self._record_specs(specs)["provenance"], "pure")

    def test_embedded_graph_omits_virtual_defaults(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                defaults = ["defaults-release"] if explicit else []
                specs = {
                    "a": _spec("a", runtime_requires=["dep"] + defaults),
                    "dep": _spec("dep", runtime_requires=defaults),
                    "defaults-release": _spec("defaults-release"),
                }
                graph = self._record_specs(specs)["dependency_graph"]
                self.assertEqual(graph, {"dep": [], "a": ["dep"]})
                self.assertEqual(list(graph), ["a", "dep"])

    def test_embedded_graph_alphabetical_without_topological_sort(self):
        specs = {
            "a": _spec("a", runtime_requires=["zlib", "library", "library"]),
            "library": _spec("library", runtime_requires=["zlib"]),
            "zlib": _spec("zlib"),
            "unrelated": _spec("unrelated"),
        }
        with patch("bits_helpers.deps.topological_sort",
                   side_effect=AssertionError("metadata must not topologically sort")):
            graph = self._record_specs(specs)["dependency_graph"]
        self.assertEqual(json.dumps(graph), json.dumps({
            "a": ["library", "zlib"], "library": ["zlib"], "zlib": []}))

    def test_embedded_graph_stable_across_runs(self):
        # Exercise the real metadata serializer in fresh interpreters: changing
        # PYTHONHASHSEED inside this process would not change its hash seed.
        code = '''
import json
from types import SimpleNamespace
from tests.test_provenance import _spec
from bits_helpers.build import create_provenance_info

edges = {"app": ["beta", "alpha"], "alpha": ["base"],
         "beta": ["base"], "base": []}
specs = {p: _spec(p, requires=edges[p], runtime_requires=edges[p])
         for p in set(edges)}
specs["defaults-release"] = _spec("defaults-release")
args = SimpleNamespace(annotate={}, architecture="arch", defaults=["release"])
for extra in (False, True):
    if extra:
        specs["unrelated"] = _spec("unrelated", requires=["base"],
                                   runtime_requires=["base"])
    record = json.loads(create_provenance_info("app", specs, args))
    print(json.dumps(record["dependency_graph"]))
'''
        expected = json.dumps({"alpha": ["base"], "app": ["alpha", "beta"],
                               "base": [], "beta": ["base"]})
        outputs = []
        for seed in ("1", "3"):
            with self.subTest(seed=seed):
                output = subprocess.check_output(
                    [sys.executable, "-c", code], text=True,
                    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    env=dict(os.environ, PYTHONHASHSEED=seed, BITS_DIST_HASH="x"))
                # Compare serialized bytes/order, not just dictionary equality.
                self.assertEqual(output.splitlines(), [expected, expected])
                outputs.append(output)
        self.assertEqual(outputs[0], outputs[1])

    def test_provenance_loose_when_closure_has_untracked(self):
        # untracked_requires decouples a dependency from the hash -> loose.
        specs = {
            "a": _spec("a", untracked_requires=["dep"]),
            "dep": _spec("dep"),
        }
        self.assertEqual(self._record_specs(specs)["provenance"], "loose")


class TestBuildIdFromManifest(unittest.TestCase):
    """build_id_from_manifest reconstructs the canonical id from a manifest dict."""

    def _manifest(self, defaults, pkgs):
        return {"defaults": defaults, "packages": pkgs}

    def test_matches_compute_build_id(self):
        pkgs = [
            {"package": "a", "version": "1", "revision": "1", "hash": "h1"},
            {"package": "b", "version": "2", "revision": "3", "hash": "h2"},
        ]
        m = self._manifest(["release", "gcc15"], pkgs)
        specs = {p["package"]: p for p in pkgs}
        args = SimpleNamespace(defaults=["release", "gcc15"], architecture="x")
        self.assertEqual(pv.build_id_from_manifest(m), pv.compute_build_id(specs, args))

    def test_order_independent(self):
        pkgs = [
            {"package": "a", "version": "1", "revision": "1", "hash": "h1"},
            {"package": "b", "version": "2", "revision": "3", "hash": "h2"},
        ]
        a = pv.build_id_from_manifest(self._manifest(["release"], pkgs))
        b = pv.build_id_from_manifest(self._manifest(["release"], list(reversed(pkgs))))
        self.assertEqual(a, b)

    def test_label_from_defaults(self):
        m = self._manifest(["release", "gcc15"],
                           [{"package": "a", "hash": "h1"}])
        self.assertTrue(pv.build_id_from_manifest(m).startswith("release_gcc15-"))

    def test_hashless_packages_excluded(self):
        with_sys = self._manifest(["release"], [
            {"package": "a", "hash": "h1"},
            {"package": "sys", "hash": ""},      # system pkg, no content hash
        ])
        without = self._manifest(["release"], [{"package": "a", "hash": "h1"}])
        self.assertEqual(pv.build_id_from_manifest(with_sys),
                         pv.build_id_from_manifest(without))

    def test_unusable_input_never_raises(self):
        self.assertEqual(pv.build_id_from_manifest("not a dict"), "")
        self.assertTrue(pv.build_id_from_manifest({}).startswith("local-"))


if __name__ == "__main__":
    unittest.main()


class TestRecursiveDependencyAlphabeticalOrder(unittest.TestCase):
    """Recursive deps use alphabetical order; direct deps keep declaration order."""

    def _record(self, package, specs, build_order):
        args = SimpleNamespace(annotate={}, architecture="arch",
                               defaults=["release"], build_order=build_order)
        os.environ["BITS_DIST_HASH"] = "deadbeef"
        try:
            return json.loads(create_provenance_info(package, specs, args))
        finally:
            os.environ.pop("BITS_DIST_HASH", None)

    def test_recursive_runtime_in_alphabetical_order(self):
        specs = {
            "app": _spec("app",
                         runtime_requires=["z", "a"],
                         full_runtime_requires={"z", "a", "m"}),
            "z": _spec("z"), "a": _spec("a"), "m": _spec("m"),
        }
        rec = self._record("app", specs, ["z", "m", "a", "app"])
        got = [d["name"] for d in rec["dependencies"]["recursive"]["runtime"]]
        self.assertEqual(got, ["a", "m", "z"])
        direct = [d["name"] for d in rec["dependencies"]["direct"]["runtime"]]
        self.assertEqual(direct, ["z", "a"])              # declaration order kept

    def test_recursive_build_in_alphabetical_order(self):
        specs = {
            "app": _spec("app", full_build_requires={"tool2", "tool1"}),
            "tool1": _spec("tool1"), "tool2": _spec("tool2"),
        }
        rec = self._record("app", specs, ["tool2", "tool1", "app"])
        got = [d["name"] for d in rec["dependencies"]["recursive"]["build"]]
        self.assertEqual(got, ["tool1", "tool2"])

    def test_no_build_order_falls_back_cleanly(self):
        args = SimpleNamespace(annotate={}, architecture="arch", defaults=["release"])
        specs = {"app": _spec("app", full_runtime_requires={"z", "a"}),
                 "a": _spec("a"), "z": _spec("z")}
        os.environ["BITS_DIST_HASH"] = "x"
        try:
            rec = json.loads(create_provenance_info("app", specs, args))
        finally:
            os.environ.pop("BITS_DIST_HASH", None)
        self.assertEqual(
            [d["name"] for d in rec["dependencies"]["recursive"]["runtime"]], ["a", "z"])
