"""Part 1 of the post-relocate out-of-package fix: cvmfs-publish must FAIL LOUD
(never silently drop) when post-relocate.sh writes files outside the package's
own tree, because publish_one only tars pkgroot. Tests the pure detection
helpers _files_under / _writes_outside_pkgroot.
"""
import os
import tempfile

from bits_helpers.cvmfs_publish import _files_under, _writes_outside_pkgroot


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()


def test_detects_file_written_outside_pkgroot():
    with tempfile.TemporaryDirectory() as work:
        pkgroot = os.path.join(work, "x86_64-el9", "fam", "PkgA", "1.0")
        _touch(os.path.join(pkgroot, ".meta.json"))
        before = _files_under(work)
        # post-relocate writes a shared file OUTSIDE pkgroot (e.g. a toolchain ns)
        _touch(os.path.join(work, "etc", "toolchain", "modulefiles", "Toolchain"))
        leaked = _writes_outside_pkgroot(before, _files_under(work), pkgroot)
        assert leaked == [os.path.join(work, "etc", "toolchain", "modulefiles", "Toolchain")]


def test_files_inside_pkgroot_are_not_flagged():
    with tempfile.TemporaryDirectory() as work:
        pkgroot = os.path.join(work, "arch", "PkgA", "1.0")
        _touch(os.path.join(pkgroot, ".meta.json"))
        before = _files_under(work)
        # post-relocate adds files INSIDE the package tree -> fine, tar captures them
        _touch(os.path.join(pkgroot, "bin", "tool"))
        _touch(os.path.join(pkgroot, "etc", "modulefiles", "PkgA"))
        assert _writes_outside_pkgroot(before, _files_under(work), pkgroot) == []


def test_preexisting_outside_files_not_flagged():
    # only NEW files (after - before) are flagged; extraction artifacts already
    # outside pkgroot before relocate are not attributed to post-relocate
    with tempfile.TemporaryDirectory() as work:
        pkgroot = os.path.join(work, "arch", "PkgA", "1.0")
        _touch(os.path.join(pkgroot, ".meta.json"))
        _touch(os.path.join(work, "sibling-preexisting"))
        before = _files_under(work)
        assert _writes_outside_pkgroot(before, _files_under(work), pkgroot) == []


def test_pkgroot_prefix_is_boundary_safe():
    # a sibling dir sharing a name prefix with pkgroot must count as outside
    with tempfile.TemporaryDirectory() as work:
        pkgroot = os.path.join(work, "arch", "PkgA", "1.0")
        _touch(os.path.join(pkgroot, ".meta.json"))
        before = _files_under(work)
        _touch(os.path.join(work, "arch", "PkgA", "1.0-extra", "f"))  # not under pkgroot
        leaked = _writes_outside_pkgroot(before, _files_under(work), pkgroot)
        assert leaked == [os.path.join(work, "arch", "PkgA", "1.0-extra", "f")]
