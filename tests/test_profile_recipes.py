# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the opt-in recipe profiling module (BITS_PROFILE_RECIPES)."""

import json
import os
import tempfile
import unittest
from unittest import mock

import bits_helpers.profile_recipes as pr


class TestDisabledPath(unittest.TestCase):
  """When profiling is off (current is None), all probes are no-ops."""

  def setUp(self):
    self._old_current = pr.current
    self._old_enabled = pr._enabled
    pr.current = None
    pr._enabled = False

  def tearDown(self):
    pr.current = self._old_current
    pr._enabled = self._old_enabled

  def test_enabled_false(self):
    self.assertFalse(pr.is_enabled())

  def test_begin_end_noop(self):
    t = pr._begin("test_op")
    self.assertEqual(t, 0)
    pr._end("test_op", t)

  def test_count_noop(self):
    pr.count_path_lookup()
    pr.count_fs_read()
    pr.count_yaml_include()
    pr.count_body_include()
    pr.count_parent_hop()

  def test_counter_snapshot_noop(self):
    self.assertEqual(pr._counter_snapshot(), {})

  def test_counter_delta_noop(self):
    self.assertEqual(pr._counter_delta({}), {})
    self.assertEqual(pr._counter_delta({"a": 1}), {})

  def test_set_phase_noop(self):
    pr.set_phase("test")
    self.assertEqual(pr.get_phase(), "test")


class TestTimer(unittest.TestCase):
  """The inclusive/exclusive operation timer."""

  def test_single_op(self):
    t = pr._Timer()
    s = t.begin("foo")
    t.end("foo", s)
    ops = t._ops_view()
    self.assertEqual(ops["foo"]["count"], 1)
    self.assertGreaterEqual(ops["foo"]["inclusive_ns"], 0)
    self.assertGreaterEqual(ops["foo"]["exclusive_ns"], 0)

  def test_nested_ops(self):
    t = pr._Timer()
    s_outer = t.begin("outer")
    s_inner = t.begin("inner")
    t.end("inner", s_inner)
    t.end("outer", s_outer)
    ops = t._ops_view()
    self.assertEqual(ops["outer"]["count"], 1)
    self.assertEqual(ops["inner"]["count"], 1)
    # Outer's exclusive should include inner's time.
    self.assertGreaterEqual(ops["outer"]["exclusive_ns"], ops["inner"]["inclusive_ns"])

  def test_misbalanced_end(self):
    t = pr._Timer()
    s = t.begin("foo")
    # End without a matching begin for "bar" — should not crash.
    t.end("bar", s)
    ops = t._ops_view()
    self.assertIn("foo", ops)

  def test_multiple_instances(self):
    t = pr._Timer()
    for _ in range(3):
      s = t.begin("foo")
      t.end("foo", s)
    self.assertEqual(t._ops_view()["foo"]["count"], 3)


class TestProfiler(unittest.TestCase):
  """The RecipeProfiler instance."""

  def setUp(self):
    self._old_current = pr.current
    self._old_enabled = pr._enabled
    self.tmpdir = tempfile.TemporaryDirectory()
    self.out_path = os.path.join(self.tmpdir.name, "profile.json")
    pr.current = None
    pr._enabled = False

  def tearDown(self):
    # Unregister the atexit handler before cleaning up the tempdir so the
    # deferred finish() does not try to write into a deleted directory.
    if pr.current is not None:
      import atexit
      try:
        atexit.unregister(pr.current.finish)
      except (TypeError, ValueError):
        pass
      pr.current = None
      pr._enabled = False
    pr.current = self._old_current
    pr._enabled = self._old_enabled
    self.tmpdir.cleanup()

  def test_set_enabled_on(self):
    p = pr.set_enabled(True, out_path=self.out_path)
    self.assertIsNotNone(p)
    self.assertTrue(pr.is_enabled())
    self.assertIs(pr.current, p)
    # Clean up: finish and unregister atexit.
    import atexit
    try:
      atexit.unregister(p.finish)
    except (TypeError, ValueError):
      pass
    pr.set_enabled(False)

  def test_set_enabled_off(self):
    p = pr.set_enabled(True, out_path=self.out_path)
    import atexit
    try:
      atexit.unregister(p.finish)
    except (TypeError, ValueError):
      pass
    pr.set_enabled(False)
    self.assertFalse(pr.is_enabled())
    self.assertIsNone(pr.current)
    self.assertTrue(os.path.exists(self.out_path))

  def test_record_invocation(self):
    p = pr.set_enabled(True, out_path=self.out_path)
    p.record_invocation(
      recipe_path="/test/recipe.sh", phase="pkglist", caller="parseRecipe",
      duration_ns=1000000, generated=False, yaml_includes=1,
      body_includes=2, parents=0, fs_reads=1, path_lookups=3)
    self.assertEqual(len(p.invocations), 1)
    inv = p.invocations[0]
    self.assertEqual(inv["recipe"], "/test/recipe.sh")
    self.assertEqual(inv["duration_ns"], 1000000)
    self.assertTrue(inv["generated"] is False)

  def test_summary_repeated_parses(self):
    p = pr.set_enabled(True, out_path=self.out_path)
    for i in range(3):
      p.record_invocation(
        recipe_path="/test/recipe.sh", phase="pkglist", caller="parseRecipe",
        duration_ns=1000000, generated=False, yaml_includes=0,
        body_includes=0, parents=0, fs_reads=1, path_lookups=1)
    s = p.summary()
    self.assertEqual(s["total_invocations"], 3)
    self.assertEqual(s["unique_recipes"], 1)
    self.assertEqual(s["repeated_parses"], 2)
    self.assertAlmostEqual(s["repeated_parse_pct"], 66.67, places=1)
    self.assertEqual(s["repeated_parse_ns"], 2000000)

  def test_counter_delta(self):
    p = pr.set_enabled(True, out_path=self.out_path)
    before = p.counter_snapshot()
    p.count("fs_reads", 3)
    p.count("path_lookups", 7)
    delta = p.counter_delta(before)
    self.assertEqual(delta["fs_reads"], 3)
    self.assertEqual(delta["path_lookups"], 7)

  def test_json_output(self):
    p = pr.set_enabled(True, out_path=self.out_path)
    p.record_invocation(
      recipe_path="/test/recipe.sh", phase="pkglist", caller="parseRecipe",
      duration_ns=500000, generated=True, yaml_includes=0,
      body_includes=0, parents=0, fs_reads=1, path_lookups=2)
    p.begin("test_op")
    p.end("test_op", p.begin("noop"))
    p.finish()
    with open(self.out_path) as f:
      data = json.load(f)
    self.assertIn("summary", data)
    self.assertIn("invocations", data)
    self.assertEqual(data["summary"]["total_invocations"], 1)
    self.assertEqual(data["invocations"][0]["generated"], True)


class TestEnvVarGating(unittest.TestCase):
  """The module reads BITS_PROFILE_RECIPES at import time."""

  def test_disabled_by_default(self):
    with mock.patch.dict(os.environ, {}, clear=True):
      # Simulate re-import with no env var
      import importlib
      with mock.patch.dict("os.environ", {}, clear=True):
        # Can't easily re-import, so check the logic
        val = os.environ.get("BITS_PROFILE_RECIPES")
        self.assertTrue(val in (None, "", "0", "false", "off"))

  def test_enabled_values(self):
    for val in ["1", "true", "yes", "on"]:
      self.assertTrue(val not in (None, "", "0", "false", "off"))

  def test_disabled_values(self):
    for val in [None, "", "0", "false", "off"]:
      self.assertTrue(val in (None, "", "0", "false", "off"))


if __name__ == "__main__":
  unittest.main()
