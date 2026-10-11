# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""BUILD_EPOCH: a change to the bits files that shape a build is a decision."""

import unittest
from collections import OrderedDict
from unittest import mock

from bits_helpers import build_epoch, hashing


class BuildEpochTest(unittest.TestCase):
  def test_covered_files_are_unchanged_or_the_epoch_was_considered(self):
    got = build_epoch.covered_sha256()
    self.assertEqual(
      got, build_epoch.COVERED_SHA256,
      "\n%s changed. If the change can alter what a build produces (the build\n"
      "environment, the generated init.sh, what relocation bakes in, the layout\n"
      "of INSTALLROOT), bump BUILD_EPOCH in bits_helpers/build_epoch.py: every\n"
      "package then rebuilds once. Either way, set COVERED_SHA256 to\n  %s\n"
      % (", ".join(build_epoch.COVERED), got))

  def _hashes(self):
    spec = {"package": "zlib", "version": "1.3", "recipe": "make", "commit_hash": "v1.3",
            "tag": "v1.3", "scm_refs": {"refs/tags/v1.3": "abc"}, "is_devel_pkg": False,
            "requires": [], "env": OrderedDict(), "append_path": OrderedDict(),
            "prepend_path": OrderedDict()}
    hashing.storeHashes("zlib", {"zlib": spec}, considerRelocation=False)
    return (spec["remote_revision_hash"], spec["local_revision_hash"],
            tuple(spec["remote_hashes"]), tuple(spec["local_hashes"]))

  # This spec's hashes from before BUILD_EPOCH existed: at 0 they must not move.
  GOLDEN_REMOTE = "7260d60f4b4ef9a6fb636a73939bb5cc551d38fb"

  def test_epoch_zero_leaves_hashes_alone(self):
    with mock.patch.object(hashing, "BUILD_EPOCH", 0):
      self.assertEqual(self._hashes()[0], self.GOLDEN_REMOTE)

  def test_a_bump_changes_every_hash(self):
    with mock.patch.object(hashing, "BUILD_EPOCH", 0):
      zero = self._hashes()
    with mock.patch.object(hashing, "BUILD_EPOCH", 1):
      one = self._hashes()
    with mock.patch.object(hashing, "BUILD_EPOCH", 2):
      two = self._hashes()
    for a, b in ((zero, one), (one, two), (zero, two)):
      self.assertTrue(all(x != y for x, y in zip(a, b)), (a, b))
      self.assertFalse(set(a[2] + a[3]) & set(b[2] + b[3]))

if __name__ == "__main__":
  unittest.main()
