# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""create_deps_info(): the runtime dependency graph recorded in each package's
.meta.json as the dependency_graph field."""

import json
import os
from types import SimpleNamespace
import unittest

from bits_helpers.build import create_deps_info, create_provenance_info


def _spec(name, **kw):
    base = {
        "package": name, "version": "1.0", "revision": "1", "hash": "h" + name,
        "tag": None, "source": None, "requires": [],
        "build_requires": [], "runtime_requires": [],
        "full_build_requires": [], "full_runtime_requires": [],
    }
    base.update(kw)
    return base


def _specs():
    # c -> b -> a, plus a build-only dep the runtime edges must omit.
    return {
        "defaults-release": _spec("defaults-release"),
        "a": _spec("a"),
        "tools": _spec("tools"),
        "b": _spec("b", runtime_requires=["a"], requires=["a"],
                   full_runtime_requires=["a"]),
        "c": _spec("c", runtime_requires=["b"], build_requires=["tools"],
                   requires=["b", "tools"], full_runtime_requires=["a", "b"]),
    }


_ARGS = SimpleNamespace(architecture="arch", defaults=["release"])


class TestDepsInfo(unittest.TestCase):

    def test_mapping_in_build_order(self):
        graph = create_deps_info("c", _specs(), _ARGS)
        self.assertEqual(graph, {"defaults-release": [],
                                 "a": ["defaults-release"],
                                 "b": ["defaults-release", "a"],
                                 "c": ["defaults-release", "b"]})
        self.assertEqual(list(graph), ["defaults-release", "a", "b", "c"])

    def test_same_edges_as_bits_deps_outmake(self):
        from bits_helpers.deps import deps_makefile
        rules = {line.split(":")[0]: line.partition(":")[2].split()
                 for line in deps_makefile(_specs(), "c", runtime_only=True).splitlines()
                 if not line.startswith("#")}
        self.assertEqual(create_deps_info("c", _specs(), _ARGS), rules)

    def test_build_only_dependency_excluded(self):
        self.assertNotIn("tools", create_deps_info("c", _specs(), _ARGS))


class TestGraphInMeta(unittest.TestCase):
    """The graph travels in .meta.json as its own last field."""

    def _record(self):
        args = SimpleNamespace(annotate={}, architecture="arch",
                               defaults=["release"], reusePolicy="strict")
        os.environ["BITS_DIST_HASH"] = "deadbeef"
        try:
            return json.loads(create_provenance_info("c", _specs(), args))
        finally:
            os.environ.pop("BITS_DIST_HASH", None)

    def test_recorded_as_last_field(self):
        rec = self._record()
        self.assertEqual(list(rec)[-1], "dependency_graph")
        self.assertEqual(rec["dependency_graph"]["c"], ["defaults-release", "b"])

    def test_dependencies_block_untouched(self):
        deps = self._record()["dependencies"]
        self.assertEqual(sorted(deps), ["direct", "recursive"])
        self.assertEqual([e["name"] for e in deps["direct"]["runtime"]], ["b"])

    def test_covers_the_recursive_closure(self):
        rec = self._record()
        closure = {e["name"] for e in rec["dependencies"]["recursive"]["runtime"]}
        self.assertTrue(closure <= set(rec["dependency_graph"]))


if __name__ == "__main__":
    unittest.main()
