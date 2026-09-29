# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the ported producer helpers in bits_helpers.cvmfs_publish.

These cover the bits that were hand-written bash in cvmfs-prepub-publish.yml and
carry hard-won fixes (template expansion, the reused-artefact re-root, the
INSTALLROOT symlink relativiser, sanitize). The stage/submit/pipeline parts need
a build host and are proven separately via the remote-runner."""
import os
import shutil
import tempfile
import unittest

import json

from bits_helpers.cvmfs_publish import (
    expand_tmpl, repo_relative_path, relativise_symlinks, sanitize,
    resolve_pkg_path, tree_fingerprint)


class TestTreeFingerprint(unittest.TestCase):
    def _tree(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "bin"))
        with open(os.path.join(d, "bin", "x"), "w") as fh:
            fh.write("hello")
        os.symlink("../bin/x", os.path.join(d, "bin", "l"))
        return d

    def test_mtime_independent(self):
        # the catalog hash embeds mtime (relocation stamps it); the content
        # fingerprint must NOT, or no two runs could ever match.
        d = self._tree(); f1 = tree_fingerprint(d)
        os.utime(os.path.join(d, "bin", "x"), (1, 1))
        self.assertEqual(f1, tree_fingerprint(d))

    def test_content_sensitive(self):
        d = self._tree(); f1 = tree_fingerprint(d)
        with open(os.path.join(d, "bin", "x"), "w") as fh:
            fh.write("HELLO")
        self.assertNotEqual(f1, tree_fingerprint(d))

    def test_mode_and_symlink_sensitive(self):
        d = self._tree(); f1 = tree_fingerprint(d)
        os.chmod(os.path.join(d, "bin", "x"), 0o755)
        self.assertNotEqual(f1, tree_fingerprint(d))


class TestResolvePkgPath(unittest.TestCase):
    def _meta(self, **templates):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, ".meta.json"), "w") as fh:
            json.dump({"cvmfs_templates": dict(prefix="/cvmfs/r", **templates)}, fh)
        return d

    def test_non_shared_arch_uses_the_path_template(self):
        d = self._meta(path="{prefix}/el9/Packages/{pkg}/{version}",
                       shared="{prefix}/shared/{pkg}/{version}")
        self.assertEqual(
            resolve_pkg_path(d, "r", "O2", "1.0", "1.0", "", "", "", "", "", "",
                             kind="path", tmpl_prefix="", arch="el9-x86"),
            "el9/Packages/O2/1.0")

    def test_modules_kind_uses_the_modules_template(self):
        d = self._meta(path="{prefix}/el9/Packages/{pkg}/{version}",
                       modules="{prefix}/el9/Modules/modulefiles/{pkg}")
        self.assertEqual(
            resolve_pkg_path(d, "r", "O2", "1.0", "1.0", "", "", "", "", "", "",
                             kind="modules", tmpl_prefix="", arch="el9"),
            "el9/Modules/modulefiles/O2")

    def test_shared_arch_uses_the_shared_template(self):
        # NEGATIVE CONTROL: selecting shared unconditionally would give the wrong
        # path for a normal package and change the relocated bytes (the hash).
        d = self._meta(path="{prefix}/el9/Packages/{pkg}/{version}",
                       shared="{prefix}/shared/{pkg}/{version}")
        self.assertEqual(
            resolve_pkg_path(d, "r", "noarch", "1.0", "1.0", "", "", "", "", "", "",
                             kind="path", tmpl_prefix="", arch="shared"),
            "shared/noarch/1.0")

    def test_share_arch_uses_the_shared_template(self):
        # Noarch packages carry effective_architecture "share" (arch.SHARED_ARCH).
        d = self._meta(path="{prefix}/el9/Packages/{pkg}/{version}",
                       shared="{prefix}/shared/{pkg}/{version}")
        self.assertEqual(
            resolve_pkg_path(d, "r", "noarch", "1.0", "1.0", "", "", "", "", "", "",
                             kind="path", tmpl_prefix="", arch="share"),
            "shared/noarch/1.0")

    def test_build_templates_override_the_package_meta(self):
        # A reused package carries its builder's layout; the publishing build's
        # templates place it instead (no re-root).
        d = self._meta(path="{prefix}/releases/{platform}/Packages/{pkg}/{tag}")
        tm = {"prefix": "/cvmfs/r/lhcb/releases",
              "path": "{prefix}/LCG_110/{pkg}/{version}/{arch}"}
        self.assertEqual(
            resolve_pkg_path(d, "r", "AIDA", "3.2.1-2", "3.2.1", "2", "x86_64-el9",
                             "", "", "", "", kind="path", tmpl_prefix="",
                             arch="x86_64-el9-gcc14-opt",
                             prefix_fallback="/cvmfs/r", templates=tm),
            "lhcb/releases/LCG_110/AIDA/3.2.1/x86_64-el9-gcc14-opt")

    def test_unresolved_token_is_refused(self):
        # An unknown token (e.g. {arch} for an older bits) must not publish
        # to a literal "{...}" directory.
        d = self._meta(path="{prefix}/{pkg}/{nope}")
        with self.assertRaises(ValueError):
            resolve_pkg_path(d, "r", "O2", "1.0", "1.0", "", "", "", "", "", "",
                             kind="path", tmpl_prefix="", arch="el9")


class TestExpandTmpl(unittest.TestCase):
    def test_family_carries_its_own_slash(self):
        # non-empty family -> "MCGenerators/ROOT"; the template uses {family}{pkg}
        self.assertEqual(
            expand_tmpl("{family}{pkg}/{version}", pkg="ROOT", version="v6",
                        family="MCGenerators"),
            "MCGenerators/ROOT/v6")

    def test_empty_family_collapses_without_a_stray_slash(self):
        self.assertEqual(
            expand_tmpl("{family}{pkg}/{version}", pkg="O2", version="daily"),
            "O2/daily")

    def test_all_tokens_substituted(self):
        got = expand_tmpl("{pkg}-{tag}-{revision}-{platform}-{user}",
                          pkg="a", tag="1", revision="2", platform="el9", user="u")
        self.assertEqual(got, "a-1-2-el9-u")


class TestRepoRelativePath(unittest.TestCase):
    def test_strips_the_repo_prefix(self):
        self.assertEqual(
            repo_relative_path("/cvmfs/test.cvmfs.io/el9/Packages/O2/1.0",
                               "test.cvmfs.io"),
            "el9/Packages/O2/1.0")

    def test_re_roots_a_reused_artefact(self):
        # a from_store package baked with another community's root is re-rooted
        # to this community's prefix (the §31 "re-rooting reused artefact" log).
        self.assertEqual(
            repo_relative_path("/cvmfs/bits.cern.ch/alice/Packages/O2/1.0",
                               "test.cvmfs.io",
                               meta_root="/cvmfs/bits.cern.ch/alice",
                               prefix_fallback="/cvmfs/test.cvmfs.io"),
            "Packages/O2/1.0")

    def test_root_below_the_community_prefix_is_kept(self):
        # Testbed: /cvmfs/test.cvmfs.io/lhcb/releases is inside the community
        # prefix /cvmfs/test.cvmfs.io and must not be flattened onto it.
        self.assertEqual(
            repo_relative_path("/cvmfs/test.cvmfs.io/lhcb/releases/LCG_110/X",
                               "test.cvmfs.io",
                               meta_root="/cvmfs/test.cvmfs.io/lhcb/releases",
                               prefix_fallback="/cvmfs/test.cvmfs.io"),
            "lhcb/releases/LCG_110/X")

    def test_dot_segments_are_refused(self):
        for bad in ("/cvmfs/r/g/../other/x", "/cvmfs/r/g/./x"):
            with self.assertRaises(ValueError):
                repo_relative_path(bad, "r", meta_root="/cvmfs/r/g",
                                   prefix_fallback="/cvmfs/r")

    def test_prefix_community_mismatch_is_refused(self):
        # a path that ends up NOT under /cvmfs/<repo>/ is a misconfiguration.
        with self.assertRaises(ValueError):
            repo_relative_path("/cvmfs/other.cern.ch/x", "test.cvmfs.io")


class TestRelativiseSymlinks(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        os.makedirs(os.path.join(self.d, "bin"))
        os.makedirs(os.path.join(self.d, "lib"))
        open(os.path.join(self.d, "lib", "libfoo.so"), "w").close()

    def test_installroot_abs_symlink_is_relativised(self):
        os.symlink("/build/INSTALLROOT/abc/pkg/1.0/lib/libfoo.so",
                   os.path.join(self.d, "bin", "foo"))
        self.assertEqual(relativise_symlinks(self.d), 1)
        self.assertEqual(os.readlink(os.path.join(self.d, "bin", "foo")),
                         "../lib/libfoo.so")

    def test_system_abs_symlink_is_left_untouched(self):
        # NEGATIVE CONTROL: a non-INSTALLROOT absolute link must NOT be rewritten
        # (rewriting it would break a legitimate system reference).
        os.symlink("/usr/lib/libc.so", os.path.join(self.d, "bin", "sys"))
        self.assertEqual(relativise_symlinks(self.d), 0)
        self.assertEqual(os.readlink(os.path.join(self.d, "bin", "sys")),
                         "/usr/lib/libc.so")


class TestSanitize(unittest.TestCase):
    def test_counts_hardlinks_and_removes_special_files_and_reports_abssym(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        a = os.path.join(d, "a"); open(a, "w").close()
        os.link(a, os.path.join(d, "b"))            # hardlink pair
        os.symlink("/etc/passwd", os.path.join(d, "l"))  # remaining abs symlink
        try:
            os.mkfifo(os.path.join(d, "fifo"))      # unpublishable special
            have_fifo = True
        except (AttributeError, OSError):
            have_fifo = False
        res = sanitize(d)
        self.assertEqual(res["hardlinks"], 2)       # both members counted
        self.assertEqual(res["abs_symlinks"], 1)
        if have_fifo:
            self.assertEqual(res["specials_removed"], 1)
            self.assertFalse(os.path.exists(os.path.join(d, "fifo")))


class TestOrderBiggestFirst(unittest.TestCase):
    def _tars(self, sizes):
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        for name, size in sizes:
            d = os.path.join(t, "el9", name); os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "%s-1.0.el9.tar.gz" % name), "wb") as fh:
                fh.write(b"x" * size)
        return t

    def test_largest_first_missing_tar_last(self):
        from bits_helpers.cvmfs_publish import order_biggest_first
        os.environ.pop("BITS_WORK_DIR", None)   # no sentinels -> tar-size fallback
        t = self._tars([("GEANT4", 100), ("O2", 50), ("Clang", 80)])
        specs = [{"package": p, "version": "1.0"}
                 for p in ("O2", "GEANT4", "Clang", "Ghost")]   # Ghost: no tar
        self.assertEqual(
            [s["package"] for s in order_biggest_first(specs, t, "el9")],
            ["GEANT4", "Clang", "O2", "Ghost"])

    def test_orders_by_recorded_payload_not_the_uniform_tar(self):
        # The §32 bug: every publish tar is a ~4 KB relocate stub, so sizing it
        # collapsed the order to manifest order and sent the biggest payload last.
        # With recorded install sizes, order must follow the PAYLOAD.
        from bits_helpers.cvmfs_publish import order_biggest_first
        work = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, work, True)
        tars = os.path.join(work, "TARS")
        for p in ("GEANT4", "protobuf", "safe_int"):        # identical 4 KB tars
            d = os.path.join(tars, "el9", p); os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "%s-1.0-2.el9.tar.gz" % p), "wb") as fh:
                fh.write(b"x" * 4096)
        for p, sz in (("GEANT4", 1_800_000_000), ("protobuf", 212_000_000),
                      ("safe_int", 4_000)):                 # but real payloads differ
            d = os.path.join(work, ".packages", "el9", p); os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "1.0-2"), "w") as fh:
                fh.write("%d\n" % sz)
        self.addCleanup(os.environ.pop, "BITS_WORK_DIR", None)
        os.environ["BITS_WORK_DIR"] = work
        specs = [{"package": p, "version": "1.0", "revision": "2"}    # manifest order
                 for p in ("safe_int", "protobuf", "GEANT4")]
        self.assertEqual(
            [s["package"] for s in order_biggest_first(specs, tars, "el9")],
            ["GEANT4", "protobuf", "safe_int"])

    def test_empty_or_corrupt_sentinel_falls_back_not_raises(self):
        # A blank/garbage sentinel must degrade to the tar-size fallback, never raise.
        from bits_helpers.cvmfs_publish import order_biggest_first
        work = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, work, True)
        tars = os.path.join(work, "TARS")
        for p, sz in (("big", 90), ("small", 10)):
            d = os.path.join(tars, "el9", p); os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "%s-1.0-1.el9.tar.gz" % p), "wb") as fh:
                fh.write(b"x" * sz)
        for p, body in (("big", ""), ("small", "not-a-number\n")):   # blank + garbage
            d = os.path.join(work, ".packages", "el9", p); os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "1.0-1"), "w").write(body)
        self.addCleanup(os.environ.pop, "BITS_WORK_DIR", None)
        os.environ["BITS_WORK_DIR"] = work
        specs = [{"package": p, "version": "1.0", "revision": "1"} for p in ("small", "big")]
        # both sentinels unreadable -> tar-size order (big 90 > small 10)
        self.assertEqual(
            [s["package"] for s in order_biggest_first(specs, tars, "el9")], ["big", "small"])


class TestBatchDriver(unittest.TestCase):
    def _manifest(self, sizes):
        import json
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        tars = os.path.join(t, "TARS")
        pkgs = []
        for name, size in sizes:
            d = os.path.join(tars, "el9", name); os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "%s-1.0.el9.tar.gz" % name), "wb") as fh:
                fh.write(b"x" * size)
            pkgs.append({"package": name, "version": "1.0",
                         "effective_architecture": "el9"})
        m = os.path.join(t, "manifest.json")
        with open(m, "w") as fh:
            json.dump({"packages": pkgs}, fh)
        return m, tars

    def _run(self, m, tars, workers, fake):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        argv = ["--manifest", m, "--repo", "r", "--tars-root", tars,
                "--arch", "el9", "--workers", str(workers)]
        if workers > 1:                       # satisfy the concurrency gate
            argv += ["--no-stats-db", "--no-prepare-lock"]
        with mock.patch.object(cp, "publish_one", fake):
            return cp.main(argv)

    def test_workers_gt_1_requires_the_concurrency_flags(self):
        # NEGATIVE CONTROL: drop the gate and this call returns 0 instead of
        # exiting — concurrent prepares would then abort on the shared stats DB.
        m, tars = self._manifest([("a", 10)])
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        with mock.patch.object(cp, "publish_one", lambda s, c: []):
            with self.assertRaises(SystemExit):
                cp.main(["--manifest", m, "--repo", "r", "--tars-root", tars,
                         "--arch", "el9", "--workers", "4",
                         "--publish-path", "staged"])   # guard is staged-only

    def test_workers_gt_1_ok_on_ingest_default(self):
        # ingest POSTs the tar, no local prepare, so N>1 needs no extra flags.
        m, tars = self._manifest([("a", 10)])
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        with mock.patch.object(cp, "publish_one", lambda s, c: []):
            rc = cp.main(["--manifest", m, "--repo", "r", "--tars-root", tars,
                          "--arch", "el9", "--workers", "4"])   # default ingest
        self.assertEqual(rc, 0)

    def test_serial_is_manifest_order(self):
        m, tars = self._manifest([("a", 10), ("big", 100), ("c", 5)])
        seen = []
        rc = self._run(m, tars, 1, lambda spec, ctx: seen.append(spec["package"]) or [])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, ["a", "big", "c"])       # N=1: manifest order, no sort

    def test_prints_biggest_first_order_with_sizes(self):
        import io, contextlib
        m, tars = self._manifest([("small", 10), ("HUGE", 900), ("mid", 100)])
        self.addCleanup(os.environ.pop, "BITS_WORK_DIR", None)
        os.environ.pop("BITS_WORK_DIR", None)   # no sentinels -> tar-size fallback
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = self._run(m, tars, 4, lambda spec, ctx: [])
        self.assertEqual(rc, 0)
        out = err.getvalue()
        self.assertIn("biggest-first order, 3 packages", out)
        self.assertIn("900B", out)                        # sizes are printed
        # listed biggest-first: HUGE (900) before mid (100) before small (10)
        self.assertLess(out.index("HUGE@"), out.index("mid@"))
        self.assertLess(out.index("mid@"), out.index("small@"))

    def test_workers_process_all_packages(self):
        m, tars = self._manifest([("a", 10), ("big", 100), ("c", 5), ("d", 50)])
        seen = []
        import threading
        lock = threading.Lock()

        def fake(spec, ctx):
            with lock:
                seen.append(spec["package"])
            return [("job-%s" % spec["package"], "%s@1(pkg)" % spec["package"])]
        rc = self._run(m, tars, 4, fake)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(seen), ["a", "big", "c", "d"])

    def test_non_redistributable_false_is_excluded(self):
        # exact CI replica: a literal boolean false excludes; enum strings do not.
        import json
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        tars = os.path.join(t, "TARS")
        pkgs = [{"package": "keep", "version": "1.0", "effective_architecture": "el9",
                 "redistributable": "all"},
                {"package": "drop", "version": "1.0", "effective_architecture": "el9",
                 "redistributable": False}]
        for name in ("keep", "drop"):
            d = os.path.join(tars, "el9", name); os.makedirs(d)
            with open(os.path.join(d, "%s-1.0.el9.tar.gz" % name), "wb") as fh:
                fh.write(b"x")
        m = os.path.join(t, "manifest.json")
        with open(m, "w") as fh:
            json.dump({"packages": pkgs}, fh)
        seen = []
        self._run(m, tars, 1, lambda spec, ctx: seen.append(spec["package"]) or [])
        self.assertEqual(seen, ["keep"])            # 'drop' excluded, 'keep' kept

    def test_one_failure_fails_the_batch(self):
        m, tars = self._manifest([("a", 10), ("bad", 100), ("c", 5)])

        def fake(spec, ctx):
            if spec["package"] == "bad":
                raise SystemExit("boom")
            return []
        # NEGATIVE CONTROL: swallow the exception in _run_one and rc would be 0.
        self.assertEqual(self._run(m, tars, 4, fake), 1)
        self.assertEqual(self._run(m, tars, 1, fake), 1)   # serial too

    def test_concurrency_is_bounded_by_workers(self):
        m, tars = self._manifest([(chr(97 + i), 10 + i) for i in range(12)])
        import threading
        import time
        live = [0]; peak = [0]; lock = threading.Lock()

        def fake(spec, ctx):
            with lock:
                live[0] += 1; peak[0] = max(peak[0], live[0])
            time.sleep(0.02)
            with lock:
                live[0] -= 1
            return []
        self.assertEqual(self._run(m, tars, 4, fake), 0)
        self.assertLessEqual(peak[0], 4)                   # never more than N in flight
        self.assertGreater(peak[0], 1)                     # and it DID run concurrently


class TestStageTarReplaceOnConflict(unittest.TestCase):
    """stage_tar retries with `cvmfs-stage --replace` ONLY on the add-only
    UNIQUE conflict, and ONLY when the caller opted in — a genuinely-new path
    (any other failure) must never trigger the delete."""

    OK = (0, "BITS_STAGING_PREFIX=pfx\nBITS_CATALOG_HASH=abcC\n", "")
    # Path already published: cvmfs-stage's add-only attempt CONFIRMS it in the
    # repository. The only case --replace should remedy.
    CONFLICT = (1, "", "cannot extract some/path into repo: swissknife hit UNIQUE "
                       "constraint on\n  catalog.md5path -- an entry is being added "
                       "that the catalog already has.\n  It IS in the repository: "
                       "catalog abc123 covers that path at base def456.")
    # Same swissknife UNIQUE, but the path is NOT in the repository — the tar
    # holds it twice (a packaging bug). Must NOT trigger a delete-retry.
    INTAR_DUP = (1, "", "cannot extract some/path into repo: swissknife hit UNIQUE "
                        "constraint on\n  catalog.md5path -- ...\n  NOT CONFIRMED in "
                        "the repository. ... the duplicate is inside the tar and this "
                        "is\n  a packaging bug, not a publishing one.")
    OTHERFAIL = (1, "", "prepare failed with exit 3")

    def _patch(self, responses):
        import bits_helpers.cvmfs_publish as cp
        calls = []
        seq = list(responses)

        class R:
            def __init__(self, rc, out, err):
                self.returncode = rc; self.stdout = out; self.stderr = err

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return R(*seq.pop(0))
        return cp, calls, fake_run

    def _call(self, cp, fake_run, **kw):
        from unittest import mock
        with mock.patch.object(cp.subprocess, "run", fake_run):
            return cp.stage_tar("repo", "/tmp/t.tar", "some/path", "job1",
                                "http://s0", **kw)

    def test_retries_with_replace_on_conflict_when_enabled(self):
        cp, calls, fake = self._patch([self.CONFLICT, self.OK])
        self.assertEqual(self._call(cp, fake, replace_on_conflict=True),
                         ("pfx", "abcC"))
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--replace", calls[0])          # first try is add-only
        self.assertEqual(calls[1], calls[0] + ["--replace"])  # SAME argv + --replace

    def test_no_retry_when_disabled(self):
        cp, calls, fake = self._patch([self.CONFLICT])
        with self.assertRaises(SystemExit):
            self._call(cp, fake, replace_on_conflict=False)
        self.assertEqual(len(calls), 1)            # default add-only, never retries

    def test_no_retry_on_in_tar_duplicate(self):
        # NEGATIVE CONTROL: same swissknife UNIQUE, but the path is NOT published
        # (duplicate inside the tar). --replace must not fire — nothing to delete.
        cp, calls, fake = self._patch([self.INTAR_DUP])
        with self.assertRaises(SystemExit):
            self._call(cp, fake, replace_on_conflict=True)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--replace", calls[0])

    def test_no_retry_on_non_conflict_failure(self):
        # NEGATIVE CONTROL: a failure that is NOT the path-occupied conflict must
        # not delete anything, even with the flag on.
        cp, calls, fake = self._patch([self.OTHERFAIL])
        with self.assertRaises(SystemExit):
            self._call(cp, fake, replace_on_conflict=True)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--replace", calls[0])

    def test_retry_failure_preserves_original_error(self):
        cp, calls, fake = self._patch([self.CONFLICT, self.OTHERFAIL])
        with self.assertRaises(SystemExit) as cm:
            self._call(cp, fake, replace_on_conflict=True)
        self.assertEqual(len(calls), 2)
        msg = str(cm.exception)
        self.assertIn("original add-only failure", msg)
        self.assertIn("It IS in the repository", msg)   # the clearer verdict is kept

    def test_success_first_try_never_replaces(self):
        cp, calls, fake = self._patch([self.OK])
        self.assertEqual(self._call(cp, fake, replace_on_conflict=True),
                         ("pfx", "abcC"))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--replace", calls[0])


class TestMainThreadsReplaceOnConflict(unittest.TestCase):
    """--replace-on-conflict reaches publish_one via ctx (off by default)."""

    def _run_capture_ctx(self, argv):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        seen = {}

        def fake_publish_one(spec, ctx):
            seen.update(ctx)
            return []
        m = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"packages": [{"package": "p", "version": "1", "revision": "1"}]}, m)
        m.close()
        with mock.patch.object(cp, "publish_one", fake_publish_one):
            cp.main(["--manifest", m.name, "--repo", "r"] + argv)
        os.unlink(m.name)
        return seen

    def test_off_by_default(self):
        self.assertFalse(self._run_capture_ctx([]).get("replace_on_conflict"))

    def test_on_when_flag_passed(self):
        self.assertTrue(self._run_capture_ctx(
            ["--replace-on-conflict"]).get("replace_on_conflict"))


class TestMainTemplatesAndSkipped(unittest.TestCase):
    """The manifest's cvmfs_templates reach publish_one; a missing tar is reported."""

    def _main(self, manifest, fake):
        import io, contextlib
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        m = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(manifest, m); m.close()
        self.addCleanup(os.unlink, m.name)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cp, "publish_one", fake), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cp.main(["--manifest", m.name, "--repo", "r", "--tars-root", "/T"])
        return rc, out.getvalue(), err.getvalue()

    def test_manifest_templates_reach_ctx(self):
        tm = {"prefix": "/cvmfs/r/g", "path": "{prefix}/{pkg}"}
        seen = {}
        rc, _, err = self._main({"cvmfs_templates": tm, "packages": [
            {"package": "p", "version": "1"}]},
            lambda spec, ctx: seen.update(ctx) or [("J", "p@1(pkg)")])
        self.assertEqual((rc, seen["templates"]), (0, tm))
        self.assertIn("{prefix}/{pkg} (this build's templates)", err)

    def test_old_manifest_falls_back_to_package_meta(self):
        seen = {}
        _, _, err = self._main({"packages": [{"package": "p", "version": "1"}]},
                               lambda spec, ctx: seen.update(ctx) or [("J", "x")])
        self.assertIsNone(seen["templates"])
        self.assertIn("each package's own .meta.json", err)

    def test_missing_tar_is_reported_as_skipped(self):
        rc, out, _ = self._main({"packages": [{"package": "p", "version": "1"}]},
                                lambda spec, ctx: [])
        self.assertEqual(rc, 0)
        self.assertIn("SKIPPED p@1: no tarball in /T", out)


class TestPublishOneLayout(unittest.TestCase):
    """publish_one end to end up to the submit: paths and the relocate env."""

    def test_modules_use_build_arch_and_hook_gets_templates(self):
        import subprocess
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        # A package tar: <arch>/<pkg>/<ver>/ with .meta.json, modulefile and a
        # relocate hook that records BITS_CVMFS_TEMPLATES.
        src = os.path.join(t, "src"); root = os.path.join(src, "tc", "GCC", "14-1")
        os.makedirs(os.path.join(root, "etc", "modulefiles"))
        with open(os.path.join(root, ".meta.json"), "w") as fh:
            json.dump({"cvmfs_templates": {"prefix": "/cvmfs/old", "path": "{prefix}/x"}}, fh)
        with open(os.path.join(root, "etc", "modulefiles", "GCC"), "w") as fh:
            fh.write("#%Module1.0\n")
        with open(os.path.join(root, "relocate-me.sh"), "w") as fh:
            fh.write('printf %%s "$BITS_CVMFS_TEMPLATES" > "%s"\n'
                     % os.path.join(t, "seen.json"))
        tars = os.path.join(t, "TARS", "tc", "store", "ab", "abc")
        os.makedirs(tars)
        tar = os.path.join(tars, "GCC-14-1.tc.tar.gz")
        subprocess.run(["tar", "-czf", tar, "-C", src, "tc"], check=True)
        tm = {"prefix": "/cvmfs/r/g", "path": "{prefix}/{pkg}/{version}/{arch}",
              "modules": "{prefix}/{arch}/Modules/modulefiles/{pkg}"}
        ctx = {"repo": "r", "tars_root": os.path.join(t, "TARS"),
               "arch": "el9-gcc14-opt", "tmpl_prefix": "", "templates": tm,
               "prefix_fallback": "/cvmfs/r", "tmp_dir": t}
        spec = {"package": "GCC", "version": "14", "revision": "1",
                "effective_architecture": "tc"}
        paths = []
        with mock.patch.object(cp, "tar_path", lambda s, r, a: tar), \
             mock.patch.object(cp, "_publish_tar",
                               lambda c, p, *a, **k: paths.append(p) or "J"):
            cp.publish_one(spec, ctx)
        self.assertEqual(paths, ["g/GCC/14/tc", "g/el9-gcc14-opt/Modules/modulefiles/GCC"])
        with open(os.path.join(t, "seen.json")) as fh:
            self.assertEqual(json.load(fh), tm)

        # With a packages template, an already published tree (same hash) whose
        # modulefile is missing gets only the modulefile.
        ptm = dict(tm, packages="{prefix}/{arch}/{pkg}/{tag}")
        pctx = dict(ctx, templates=ptm, prepub_url="http://p", token="", submit=True)
        spec2 = dict(spec, hash="H")
        paths.clear()
        with mock.patch.object(cp, "tar_path", lambda s, r, a: tar), \
             mock.patch.object(cp, "published_state",
                               lambda c, p: {"exists": "Modules" not in p, "hash": "H"}), \
             mock.patch.object(cp, "_publish_tar",
                               lambda c, p, *a, **k: paths.append(p) or "J"):
            jobs = cp.publish_one(spec2, pctx)
        self.assertEqual(paths, ["g/el9-gcc14-opt/Modules/modulefiles/GCC"])
        self.assertEqual([lbl for _, lbl in jobs], ["GCC@14-1(modules)"])


def cp_tar_path(spec, ctx):
    import bits_helpers.cvmfs_publish as cp
    return cp.tar_path(spec, ctx["tars_root"], ctx["arch"])


class TestPackagesAndReleaseView(unittest.TestCase):
    """cvmfs_packages_template: publish once per package, release view as links."""

    TM = {"prefix": "/cvmfs/r/g",
          "packages": "{prefix}/{arch}/{family}{pkg}/{tag}",
          "path": "{prefix}/releases/LCG_110/{family}{pkg}/{version}/{platform}",
          "shared": "{prefix}/noarch/{pkg}/{tag}",
          "modules": "{prefix}/{arch}/Modules/{pkg}", "release": "LCG_110"}

    def _ctx(self, **kw):
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        ctx = {"repo": "r", "arch": "el9-gcc15-opt", "tmpl_prefix": "",
               "templates": self.TM, "prefix_fallback": "/cvmfs/r",
               "platform": "x86_64-el9", "tars_root": os.path.join(t, "TARS"),
               "tmp_dir": t, "prepub_url": "http://p", "token": "", "submit": True}
        ctx.update(kw)
        return ctx

    SPEC = {"package": "ROOT", "version": "6.36", "revision": "2", "hash": "h1",
            "effective_architecture": "el9-gcc15-opt"}

    def test_tree_goes_to_packages_and_view_to_releases(self):
        import bits_helpers.cvmfs_publish as cp
        ctx = self._ctx()
        self.assertEqual(cp.package_path(self.SPEC, ctx), "g/el9-gcc15-opt/ROOT/6.36-2")
        self.assertEqual(cp._spec_path(self.SPEC, ctx, "view"),
                         "g/releases/LCG_110/ROOT/6.36/x86_64-el9")
        noarch = dict(self.SPEC, package="six", effective_architecture="share")
        self.assertEqual(cp.package_path(noarch, ctx), "g/noarch/six/6.36-2")
        # Without a packages template there is no view: the releases path is the tree.
        tm = {k: v for k, v in self.TM.items() if k != "packages"}
        self.assertIsNone(cp._spec_path(self.SPEC, self._ctx(templates=tm), "view"))

    def test_already_published_is_skipped_or_refused(self):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        ctx = self._ctx()
        with mock.patch.object(cp, "published_state", lambda c, p: {"exists": True, "hash": "h1"}):
            with self.assertRaises(cp.AlreadyPublished):
                cp.publish_one(self.SPEC, ctx)
        with mock.patch.object(cp, "published_state", lambda c, p: {"exists": True, "hash": "other"}):
            with self.assertRaises(SystemExit):
                cp.publish_one(self.SPEC, ctx)
        # Not there / prepub cannot tell: carry on (here: no tar -> nothing).
        for st in ({"exists": False}, None):
            with mock.patch.object(cp, "published_state", lambda c, p, st=st: st):
                self.assertEqual(cp.publish_one(self.SPEC, ctx), [])

    def test_view_tar_has_relative_links(self):
        import tarfile
        import bits_helpers.cvmfs_publish as cp
        ctx = self._ctx()
        self.assertEqual(cp.view_root(ctx), "g/releases/LCG_110")
        tar = cp.build_view_tar([("g/releases/LCG_110/ROOT/6.36/x86_64-el9",
                                  "g/el9-gcc15-opt/ROOT/6.36-2")],
                                "g/releases/LCG_110", ctx["tmp_dir"])
        with tarfile.open(tar) as tf:
            m = {i.name: i for i in tf.getmembers()}
        self.assertEqual(sorted(m), ["ROOT", "ROOT/6.36", "ROOT/6.36/x86_64-el9"])
        link = m["ROOT/6.36/x86_64-el9"]
        self.assertTrue(link.issym())
        self.assertEqual(link.linkname, "../../../../el9-gcc15-opt/ROOT/6.36-2")
        self.assertEqual(os.path.normpath(os.path.join(
            "g/releases/LCG_110/ROOT/6.36", link.linkname)), "g/el9-gcc15-opt/ROOT/6.36-2")

    def _main(self, fake, extra=(), templates=None, base_state={"exists": True}):
        import io, contextlib
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        m = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"cvmfs_templates": templates or self.TM, "architecture": "el9-gcc15-opt",
                   "packages": [self.SPEC, dict(self.SPEC, package="six", hash="h2")]}, m)
        m.close(); self.addCleanup(os.unlink, m.name)
        sent = []
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cp, "publish_one", fake), \
             mock.patch.object(cp, "published_state", lambda c, p: base_state), \
             mock.patch.object(cp, "_publish_tar", lambda c, p, t, lbl, fp=None:
                               sent.append((p, lbl, c["publish_path"])) or "JV"), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cp.main(["--manifest", m.name, "--repo", "r", "--arch", "el9-gcc15-opt",
                          "--platform", "x86_64-el9", "--prefix-fallback", "/cvmfs/r"]
                         + list(extra))
        return rc, sent, out.getvalue(), err.getvalue()

    def test_release_view_published_once_over_all_packages(self):
        import bits_helpers.cvmfs_publish as cp

        def fake(spec, ctx):
            if spec["package"] == "six":
                raise cp.AlreadyPublished("g/el9-gcc15-opt/six/6.36-2")
            return [("J1", "ROOT@6.36-2(pkg)")]
        rc, sent, out, _ = self._main(fake, ["--release-view"])
        self.assertEqual(rc, 0)
        self.assertIn("SKIPPED six@6.36: already published", out)
        # One view job, always via ingest (merges into a shared release dir).
        self.assertEqual(sent, [("g/releases/LCG_110", "release-view@g/releases/LCG_110", "ingest")])
        self.assertIn("SKIPPED BASE: already published", out)
        # Without the flag: packages only.
        rc, sent, _, _ = self._main(fake)
        self.assertEqual((rc, sent), (0, []))

    def test_view_falls_back_to_the_configured_path_without_ingest(self):
        import io, contextlib
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        m = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"cvmfs_templates": self.TM, "packages": [self.SPEC]}, m); m.close()
        self.addCleanup(os.unlink, m.name)
        for ok_paths, want_rc in ((("staged",), 0), ((), 1)):
            tried = []

            def pub(c, p, t, lbl, fp=None, ok_paths=ok_paths):
                tried.append(c["publish_path"])
                self.assertFalse(c["replace_on_conflict"])
                if c["publish_path"] not in ok_paths:
                    raise SystemExit("HTTP 400: ingest not enabled")
                return "JV"
            err = io.StringIO()
            with mock.patch.object(cp, "publish_one", lambda s, c: [("J", "x")]), \
                 mock.patch.object(cp, "published_state", lambda c, p: {"exists": True}), \
                 mock.patch.object(cp, "_publish_tar", pub), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                rc = cp.main(["--manifest", m.name, "--repo", "r", "--arch", "el9-gcc15-opt",
                              "--publish-path", "staged", "--replace-on-conflict",
                              "--release-view"])
            self.assertEqual((rc, tried), (want_rc, ["ingest", "staged"]))
            if want_rc:
                self.assertIn("needs prepub's ingest path", err.getvalue())

    def test_no_release_view_when_a_package_failed(self):
        def fake(spec, ctx):
            if spec["package"] == "six":
                raise SystemExit("boom")
            return [("J1", "ROOT(pkg)")]
        rc, sent, _, err = self._main(fake, ["--release-view"])
        self.assertEqual((rc, sent), (1, []))
        self.assertIn("release view: not created", err)

    def test_no_view_without_both_templates_or_a_release(self):
        fake = lambda s, c: [("J", "x(pkg)")]
        no_pkgs = {k: v for k, v in self.TM.items() if k != "packages"}
        no_rel = dict(self.TM, path=self.TM["packages"])   # no releases template given
        main_line = dict(self.TM, release="")
        for tm, why in ((no_pkgs, "no cvmfs_packages_template"),
                        (no_rel, "no cvmfs_packages_template and cvmfs_releases_template"),
                        (main_line, "no release")):
            rc, sent, _, err = self._main(fake, ["--release-view"], templates=tm)
            self.assertEqual((rc, sent), (0, []), why)
            self.assertIn("no release view", err)

    def test_release_view_is_not_for_one_package(self):
        with self.assertRaises(SystemExit):
            self._main(lambda s, c: [], ["--release-view", "--one", "ROOT"])

    def test_skipped_package_still_gets_a_missing_modulefile(self):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        ctx = self._ctx()
        asked = []

        def state(c, p):
            asked.append(p)
            return {"exists": True, "hash": "h1"} if "Modules" not in p else {"exists": False}
        # Modulefile missing -> both paths are asked; with no tar here to take
        # it from, the package still counts as published (and stays in the view).
        with mock.patch.object(cp, "published_state", state):
            with self.assertRaises(cp.AlreadyPublished):
                cp.publish_one(self.SPEC, ctx)
        self.assertEqual(asked, ["g/el9-gcc15-opt/ROOT/6.36-2",
                                 "g/el9-gcc15-opt/Modules/ROOT/6.36-2"])
        # A noarch package's modulefile goes to the build arch, not "share".
        noarch = dict(self.SPEC, effective_architecture="share")
        self.assertEqual(cp._spec_path(noarch, ctx, "modules"), "g/el9-gcc15-opt/Modules/ROOT")

    def test_replace_on_conflict_overrides_a_different_build(self):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        with mock.patch.object(cp, "published_state", lambda c, p: {"exists": True, "hash": "other"}):
            self.assertEqual(cp.publish_one(self.SPEC, self._ctx(replace_on_conflict=True)), [])

    def test_view_root_is_a_whole_directory(self):
        import bits_helpers.cvmfs_publish as cp
        tm = dict(self.TM, path="{prefix}/releases/rel-{version}/{pkg}")
        self.assertEqual(cp.view_root(self._ctx(templates=tm)), "g/releases")
        # {arch}/{platform} are fixed for a build, so they stay in the root.
        tm = dict(self.TM, path="{prefix}/releases/{arch}/{pkg}")
        self.assertEqual(cp.view_root(self._ctx(templates=tm)), "g/releases/el9-gcc15-opt")

    def test_base_module_points_at_the_packages_dir(self):
        import subprocess
        import bits_helpers.cvmfs_publish as cp
        tm = dict(self.TM, packages="{prefix}/{arch}/Packages/{family}{pkg}/{tag}",
                  modules="{prefix}/{arch}/Modules/modulefiles/{pkg}")
        mods, text = cp.base_module(self._ctx(templates=tm))
        self.assertEqual(mods, "g/el9-gcc15-opt/Modules/modulefiles")
        self.assertIn("[file join [file dirname $ModulesCurrentModulefile] ../../../Packages]", text)
        self.assertIn("setenv BASEDIR $base_path", text)
        # Resolves to the Packages dir (checked with tclsh when available).
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        mf = os.path.join(d, mods, "BASE", "1.0")
        os.makedirs(os.path.dirname(mf))
        want = os.path.normpath(os.path.join(d, "g/el9-gcc15-opt/Packages"))
        self.assertEqual(os.path.normpath(os.path.join(os.path.dirname(mf), "../../../Packages")), want)
        if shutil.which("tclsh"):
            script = ("set ModulesCurrentModulefile %s\n" % mf + "proc setenv {k v} {puts $v}\n"
                      "proc uname {x} {return x}\n" + text.split("\n", 1)[1])
            out = subprocess.run(["tclsh"], input=script, capture_output=True, text=True).stdout
            self.assertEqual(out.strip(), want)
        # Groups without a packages template get no BASE from publish.
        self.assertIsNone(cp.base_module(self._ctx(templates={k: v for k, v in tm.items()
                                                              if k != "packages"})))

    def test_packages_outside_the_arch_dir_get_an_alias(self):
        import io, contextlib, tarfile
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        specs = [dict(self.SPEC, package="GCC", hash="g", effective_architecture="el9-gcc15"),
                 dict(self.SPEC, package="six", hash="s", effective_architecture="share"),
                 self.SPEC]
        m = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"cvmfs_templates": self.TM, "packages": specs}, m); m.close()
        self.addCleanup(os.unlink, m.name)
        got = {}

        def pub(c, p, t, lbl, fp=None):
            if lbl.startswith("aliases@"):
                with tarfile.open(t) as tf:
                    got.update({i.name: i.linkname for i in tf.getmembers() if i.issym()})
                got["root"], got["how"] = p, c["publish_path"]
            return "J"
        with mock.patch.object(cp, "publish_one", lambda s, c: [("J", "x")]), \
             mock.patch.object(cp, "published_state", lambda c, p: {"exists": "BASE" in p}), \
             mock.patch.object(cp, "_publish_tar", pub), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = cp.main(["--manifest", m.name, "--repo", "r", "--arch", "el9-gcc15-opt"])
        self.assertEqual(rc, 0)
        self.assertEqual(got, {"root": "g/el9-gcc15-opt", "how": "ingest",
                               "GCC/6.36-2": "../../el9-gcc15/GCC/6.36-2",
                               "six/6.36-2": "../../noarch/six/6.36-2"})

    def _tarball(self, ctx, spec, files, links=()):
        """A package tarball as bits writes it: <arch>/<pkg>/<ver-rev>/..."""
        import subprocess
        arch = spec["effective_architecture"]
        vdir = spec["version"] + "-" + spec["revision"]
        src = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, src, True)
        root = os.path.join(src, arch, spec["package"], vdir)
        for f in files + [".meta.json"]:
            os.makedirs(os.path.dirname(os.path.join(root, f)), exist_ok=True)
            open(os.path.join(root, f), "w").close()
        for name, target in links:
            os.makedirs(os.path.dirname(os.path.join(root, name)) or root, exist_ok=True)
            os.symlink(target, os.path.join(root, name))
        tar = cp_tar_path(spec, ctx)
        os.makedirs(os.path.dirname(tar), exist_ok=True)
        subprocess.run(["tar", "-czf", tar, "-C", src, arch], check=True)

    def test_merged_view_links_files_into_the_packages(self):
        import bits_helpers.cvmfs_publish as cp
        ctx = self._ctx()
        dep = dict(self.SPEC, package="zlib", hash="z")
        top = dict(self.SPEC, package="ROOT")
        # zlib's lib64 is a symlink to lib: walked as a directory, not linked whole.
        self._tarball(ctx, dep, ["lib/libz.so", "include/zlib.h", "etc/profile.d/init.sh",
                                 "lib/libz.so.unrelocated"], links=[("lib64", "lib")])
        self._tarball(ctx, top, ["bin/root", "lib/libz.so", "lib64/libCore.so",
                                 "lib/python3.12/site-packages/ROOT.py"])
        staging = os.path.join(ctx["tmp_dir"], "stage")
        vp = "g/views/LCG_110/el9-gcc15-opt"
        res = cp.merged_view(ctx, [dep, top], staging, vp)
        # The dependent (later) package wins; etc/ and .unrelocated stay out.
        self.assertEqual(sorted(res["linked"]), [
            "bin/root", "include/zlib.h", "lib/libz.so", "lib/python3.12/site-packages/ROOT.py",
            "lib64/libCore.so", "lib64/libz.so"])
        self.assertEqual(res["conflicts"], [("lib/libz.so", "ROOT", "zlib")])

        def resolved(rel):
            link = os.readlink(os.path.join(staging, rel))
            return os.path.normpath(os.path.join(vp, os.path.dirname(rel), link))
        self.assertEqual(resolved("lib/libz.so"), "g/el9-gcc15-opt/ROOT/6.36-2/lib/libz.so")
        self.assertEqual(resolved("include/zlib.h"), "g/el9-gcc15-opt/zlib/6.36-2/include/zlib.h")
        self.assertTrue(os.path.isdir(os.path.join(staging, "lib64")))
        # Through zlib's lib64 -> lib symlink, which the published tree also has.
        self.assertEqual(resolved("lib64/libz.so"), "g/el9-gcc15-opt/zlib/6.36-2/lib64/libz.so")
        # Excluded packages stay out.
        ctx["templates"] = dict(self.TM, view_exclude=["ROOT"])
        res = cp.merged_view(ctx, [dep, top], os.path.join(ctx["tmp_dir"], "s2"), vp)
        self.assertEqual(sorted(res["linked"]), ["include/zlib.h", "lib/libz.so", "lib64/libz.so"])

    def test_view_list_from_the_build_is_used_and_rules_apply(self):
        import subprocess
        import bits_helpers.cvmfs_publish as cp
        ctx = self._ctx()
        spec = dict(self.SPEC, package="ROOT", hash="h1")
        # The local install of this very build, with the list the build wrote.
        work = os.path.dirname(ctx["tars_root"])
        root = os.path.join(work, spec["effective_architecture"], "ROOT", "6.36-2")
        for f in ("bin/root", "share/doc/README", "etc/root/system.rootrc", "lib/libCore.so"):
            os.makedirs(os.path.dirname(os.path.join(root, f)), exist_ok=True)
            open(os.path.join(root, f), "w").close()
        with open(os.path.join(root, ".meta.json"), "w") as fh:
            json.dump({"package": {"hash": "h1"}}, fh)
        subprocess.run(["bash", os.path.join(os.path.dirname(cp.__file__), "view-list.sh"), root],
                       check=True)
        # A file added to the local tree after the build is not in the list.
        open(os.path.join(root, "bin", "added-later"), "w").close()
        vp = "g/views/LCG_110/el9-gcc15-opt"
        res = cp.merged_view(ctx, [spec], os.path.join(ctx["tmp_dir"], "a"), vp)
        self.assertEqual(sorted(res["linked"]), ["bin/root", "lib/libCore.so", "share/doc/README"])
        # The recipe's view rules (from the manifest): drop share/doc, add etc/root.
        rules = dict(spec, view={"exclude": ["share/doc"], "include": ["etc/root"]})
        res = cp.merged_view(ctx, [rules], os.path.join(ctx["tmp_dir"], "b"), vp)
        self.assertEqual(sorted(res["linked"]), ["bin/root", "etc/root/system.rootrc", "lib/libCore.so"])
        res = cp.merged_view(ctx, [dict(spec, view=False)], os.path.join(ctx["tmp_dir"], "c"), vp)
        self.assertEqual(res["linked"], [])
        # A different build at that local path is not trusted: its tarball is used.
        self._tarball(ctx, dict(spec, hash="h2"), ["bin/other"])
        res = cp.merged_view(ctx, [dict(spec, hash="h2")], os.path.join(ctx["tmp_dir"], "d"), vp)
        self.assertEqual(res["linked"], ["bin/other"])

    def test_tarball_view_list_is_preferred_over_listing(self):
        import subprocess
        import bits_helpers.cvmfs_publish as cp
        src = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, src, True)
        root = os.path.join(src, "a", "p", "1-1")
        os.makedirs(os.path.join(root, "bin"))
        open(os.path.join(root, "bin", "x"), "w").close()
        open(os.path.join(root, ".meta.json"), "w").close()
        subprocess.run(["bash", os.path.join(os.path.dirname(cp.__file__), "view-list.sh"), root],
                       check=True)
        open(os.path.join(root, "bin", "not-listed"), "w").close()
        tar = os.path.join(src, "p.tar.gz")
        subprocess.run(["tar", "-czf", tar, "-C", src, "a"], check=True)
        self.assertEqual(sorted(p for p, (k, _) in cp._tar_tree(tar).items() if k == "file"), ["bin/x"])

    def test_view_setup_locates_itself(self):
        import subprocess
        import bits_helpers.cvmfs_publish as cp
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        for sub in ("bin", "lib", "lib/python3.12/site-packages"):
            os.makedirs(os.path.join(d, sub))
        cp.write_view_setup(d, "/cvmfs/r/g/views/X/a")
        real = os.path.realpath(d)
        want = "%s/bin:/usr/bin:/bin|%s/lib/python3.12/site-packages|%s" % (real, real, real)
        for sh in ("bash", "zsh"):   # locate themselves: the mounted dir, not /cvmfs/...
            if shutil.which(sh):
                out = subprocess.run([sh, "-c", 'cd / && PATH=/usr/bin:/bin; source "%s/setup.sh" && '
                                      'echo "$PATH|$PYTHONPATH|$BITS_VIEW"' % d],
                                     capture_output=True, text=True).stdout.strip()
                self.assertEqual(out, want, sh)
        if shutil.which("dash"):     # no way to locate itself: the published path
            out = subprocess.run(["dash", "-c", '. "%s/setup.sh" 2>/dev/null; echo "$BITS_VIEW"' % d],
                                 capture_output=True, text=True).stdout.strip()
            self.assertIn(out, ("/cvmfs/r/g/views/X/a", ""))
        self.assertIn('set _v = "/cvmfs/r/g/views/X/a"', open(os.path.join(d, "setup.csh")).read())
        if shutil.which("tcsh"):
            out = subprocess.run(["tcsh", "-f", "-c", 'source "%s/setup.csh"; echo $BITS_VIEW' % d],
                                 capture_output=True, text=True).stdout.strip()
            self.assertEqual(out, "/cvmfs/r/g/views/X/a")

    def test_merged_view_published_once(self):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        tm = dict(self.TM, views="{prefix}/views/LCG_110/{arch}")   # {release} baked by the build
        ctx = self._ctx(templates=tm)
        self._tarball(ctx, self.SPEC, ["bin/root"])
        lines, sent = [], []
        with mock.patch.object(cp, "published_state", lambda c, p: {"exists": True}):
            self.assertEqual(cp._publish_merged_view(ctx, [self.SPEC], lines.extend), 0)
        self.assertEqual(lines, ["SKIPPED merged view: already published at g/views/LCG_110/el9-gcc15-opt"])
        lines.clear()
        with mock.patch.object(cp, "published_state", lambda c, p: {"exists": False}), \
             mock.patch.object(cp, "_publish_tar", lambda c, p, t, lbl, fp=None: sent.append(p) or "JM"):
            self.assertEqual(cp._publish_merged_view(ctx, [self.SPEC], lines.extend), 0)
        self.assertEqual(sent, ["g/views/LCG_110/el9-gcc15-opt"])
        self.assertEqual(lines, ["PUBLISHED JM merged-view@g/views/LCG_110/el9-gcc15-opt"])

    def test_base_module_published_when_missing(self):
        fake = lambda s, c: [("J", "x(pkg)")]
        rc, sent, _, _ = self._main(fake, base_state={"exists": False})
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [("g/el9-gcc15-opt/Modules/BASE", "BASE@g/el9-gcc15-opt/Modules(modules)", "ingest")])


def _boom(*a, **k):
    raise AssertionError("must not be called")


class TestSubmitIngest(unittest.TestCase):
    def test_posts_tar_with_sha256_and_signs_ingest_path(self):
        import hashlib
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        import bits_helpers.prepub as pp
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        tarf = os.path.join(t, "p.tar"); open(tarf, "wb").write(b"hello-tar-bytes")
        want = hashlib.sha256(b"hello-tar-bytes").hexdigest()
        cap = {}

        class Resp:
            status_code = 200; text = ""
            def json(self): return {"job_id": "JID-1"}

        class Sess:
            def post(self, url, files=None, headers=None, timeout=None):
                cap["files"] = files; return Resp()

        def fake_auth(token, method, uri, fields=None, body_hash=None,
                      bearer_auth=False, no_verify_tls=False):
            cap["signed"] = fields; cap["body_hash"] = body_hash
            return {"Authorization": "sig"}

        with mock.patch.object(pp, "_make_session", lambda *a, **k: Sess()), \
             mock.patch.object(pp, "_signed_uri", lambda u: u), \
             mock.patch.object(pp, "_auth_headers", fake_auth):
            jid = cp.submit_ingest("http://prepub", "tok", "repo", "el9/pkg",
                                   tarf, build_id="B1")
        self.assertEqual(jid, "JID-1")
        self.assertEqual(cap["files"]["publish_path"], (None, "ingest"))
        self.assertEqual(cap["files"]["tar_sha256"], (None, want))
        self.assertEqual(cap["files"]["build_id"], (None, "B1"))
        self.assertIn("tar", cap["files"])                       # the tar is attached
        self.assertEqual(cap["signed"]["publish_path"], "ingest")   # signed set binds
        self.assertEqual(cap["signed"]["tar_sha256"], want)         # the sha + path
        self.assertEqual(cap["signed"]["build_id"], "B1")
        # the httpsig BODY hash must be the tar's sha256, or prepub 401s the upload
        self.assertEqual(cap["body_hash"], want)
        self.assertNotIn("direct_s3", cap["files"])          # off by default
        self.assertNotIn("direct_s3", cap["signed"])

    def test_direct_s3_sent_and_signed_when_enabled(self):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        import bits_helpers.prepub as pp
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        tarf = os.path.join(t, "p.tar"); open(tarf, "wb").write(b"z")
        cap = {}

        class Resp:
            status_code = 200; text = ""
            def json(self): return {"job_id": "J"}

        class Sess:
            def post(self, url, files=None, headers=None, timeout=None):
                cap["files"] = files; return Resp()

        def fake_auth(token, method, uri, fields=None, body_hash=None,
                      bearer_auth=False, no_verify_tls=False):
            cap["signed"] = fields; return {}

        with mock.patch.object(pp, "_make_session", lambda *a, **k: Sess()), \
             mock.patch.object(pp, "_signed_uri", lambda u: u), \
             mock.patch.object(pp, "_auth_headers", fake_auth):
            cp.submit_ingest("http://p", "t", "r", "el9/x", tarf, direct_s3=True)
        self.assertEqual(cap["files"]["direct_s3"], (None, "true"))   # form field
        self.assertEqual(cap["signed"]["direct_s3"], "true")          # and signed


class TestPublishTar(unittest.TestCase):
    def _tar(self):
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        p = os.path.join(t, "x.tar"); open(p, "wb").write(b"x"); return p

    def test_ingest_posts_tar_and_skips_stage(self):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        tarf = self._tar()
        with mock.patch.object(cp, "submit_ingest", lambda *a, **k: "IJID"), \
             mock.patch.object(cp, "stage_tar", _boom):        # never on ingest
            jid = cp._publish_tar(
                {"publish_path": "ingest", "prepub_url": "u", "token": "t",
                 "repo": "r", "submit": True}, "el9/p", tarf, "p@1(pkg)")
        self.assertEqual(jid, "IJID")
        self.assertFalse(os.path.exists(tarf))                 # tar removed

    def test_staged_stages_then_submits(self):
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        tarf = self._tar()
        with mock.patch.object(cp, "stage_tar", lambda *a, **k: ("PFX", "HASHC")), \
             mock.patch.object(cp, "submit_staged", lambda *a, **k: "SJID"), \
             mock.patch.object(cp, "submit_ingest", _boom):    # never on staged
            jid = cp._publish_tar(
                {"publish_path": "staged", "prepub_url": "u", "token": "t", "repo": "r",
                 "submit": True, "job_id_base": "jb", "stratum0_url": "s"},
                "el9/p", tarf, "p@1(pkg)")
        self.assertEqual(jid, "SJID")
        self.assertFalse(os.path.exists(tarf))

    def test_dry_run_staged_stages_but_does_not_submit(self):
        import io, contextlib
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        tarf = self._tar(); out = io.StringIO()
        with contextlib.redirect_stdout(out), \
             mock.patch.object(cp, "stage_tar", lambda *a, **k: ("PFX", "HASHC")), \
             mock.patch.object(cp, "submit_staged", _boom):    # dry-run: stage but no submit
            jid = cp._publish_tar(
                {"publish_path": "staged", "submit": False, "repo": "r",
                 "job_id_base": "jb", "stratum0_url": "s"},
                "el9/p", tarf, "p@1(pkg)", fp="FP9")
        self.assertEqual(jid, "HASHC")                          # catalog hash, for verify
        self.assertIn("FINGERPRINT FP9 p@1(pkg)", out.getvalue())
        self.assertFalse(os.path.exists(tarf))

    def test_dry_run_ingest_no_submit_prints_fingerprint(self):
        import io, contextlib
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        tarf = self._tar(); out = io.StringIO()
        with contextlib.redirect_stdout(out), \
             mock.patch.object(cp, "submit_ingest", _boom):    # dry-run submits nothing
            jid = cp._publish_tar({"publish_path": "ingest", "submit": False},
                                  "el9/p", tarf, "p@1(pkg)", fp="FP123")
        self.assertEqual(jid, "FP123")
        self.assertIn("FINGERPRINT FP123 p@1(pkg)", out.getvalue())
        self.assertFalse(os.path.exists(tarf))


class TestIngestConcurrencyGate(unittest.TestCase):
    def test_ingest_workers_gt1_does_not_require_stage_flags(self):
        # NEGATIVE CONTROL vs the staged gate: ingest N>1 must NOT demand
        # --no-stats-db/--no-prepare-lock (it runs no local prepare).
        import json
        from unittest import mock
        import bits_helpers.cvmfs_publish as cp
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t, True)
        m = os.path.join(t, "man.json")
        json.dump({"packages": [{"package": "a", "version": "1.0"}]}, open(m, "w"))
        with mock.patch.object(cp, "publish_one", lambda s, c: []):
            rc = cp.main(["--manifest", m, "--repo", "r", "--tars-root", t,
                          "--arch", "el9", "--publish-path", "ingest", "--workers", "4"])
        self.assertEqual(rc, 0)   # no SystemExit from the gate


if __name__ == "__main__":
    unittest.main()


class TestPublishOverlayTars(unittest.TestCase):
    """publish_overlay_tars stages each tar at the repo root (path=''), gives each
    a distinct job_id_base, and preserves the caller's tar (a temp copy is
    published). The actual stage/submit is proven on a build host separately."""

    def test_overlay_publish(self):
        import bits_helpers.cvmfs_publish as P
        calls = []

        def fake_publish_tar(ctx, path, tar, label, fp=None):
            # mimic _publish_tar: it removes the (temp) tar it publishes
            calls.append((ctx["job_id_base"], path, label, os.path.exists(tar)))
            os.remove(tar)
            return "job-" + label

        orig = P._publish_tar
        P._publish_tar = fake_publish_tar
        try:
            d = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, d, True)
            t1 = os.path.join(d, "a.tar"); open(t1, "w").write("x")
            t2 = os.path.join(d, "b.tar"); open(t2, "w").write("y")
            jids = P.publish_overlay_tars(
                {"job_id_base": "base", "tmp_dir": d}, [t1, t2])
            self.assertEqual(jids, ["job-a.tar", "job-b.tar"])
            self.assertEqual([c[1] for c in calls], ["", ""])            # root path
            self.assertEqual([c[0] for c in calls], ["base-tar0", "base-tar1"])
            self.assertTrue(all(c[3] for c in calls))                    # temp existed
            self.assertTrue(os.path.exists(t1) and os.path.exists(t2))   # originals kept
        finally:
            P._publish_tar = orig


if __name__ == "__main__":
    unittest.main()
