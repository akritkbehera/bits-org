"""Tests for the own_hash build-type-neutral architecture hook.

own_hash packages (the toolchain) drop build-type append_arch qualifiers
(-opt/-dbg, marked `own_hash_neutral: true`) from their store/deploy arch, so
one compiler build is shared across build types. Compiler qualifiers (-gcc15,
-clang) are kept. See arch.compute_own_hash_arch / effective_arch and
defaults.readDefaults collection.
"""
import os
import tempfile

from bits_helpers.arch import (
    compute_combined_arch, compute_own_hash_arch, effective_arch, SHARED_ARCH)
from bits_helpers.defaults import readDefaults


def test_own_hash_arch_drops_marked_qualifier():
    meta = {"_append_arch_qualifiers": ["-gcc15", "-opt"],
            "_own_hash_drop_qualifiers": ["-opt"]}
    assert compute_own_hash_arch(meta, ["release", "gcc15", "opt"], "x86_64-el9") \
        == "x86_64-el9-gcc15"
    assert compute_combined_arch(meta, ["release", "gcc15", "opt"], "x86_64-el9") \
        == "x86_64-el9-gcc15-opt"


def test_own_hash_arch_keeps_compiler_only():
    meta = {"_append_arch_qualifiers": ["-gcc15"]}
    assert compute_own_hash_arch(meta, ["release", "gcc15"], "x86_64-el9") \
        == "x86_64-el9-gcc15"
    assert compute_own_hash_arch(meta, ["release", "gcc15"], "x86_64-el9") \
        == compute_combined_arch(meta, ["release", "gcc15"], "x86_64-el9")


def test_own_hash_arch_drops_multiple_and_preserves_order():
    meta = {"_append_arch_qualifiers": ["-gcc15", "-cuda", "-dbg"],
            "_own_hash_drop_qualifiers": ["-dbg"]}
    assert compute_own_hash_arch(meta, [], "x86_64-el9") == "x86_64-el9-gcc15-cuda"


def test_own_hash_arch_no_qualifiers_is_raw():
    assert compute_own_hash_arch({}, ["release"], "x86_64-el9") == "x86_64-el9"


def test_own_hash_arch_legacy_qualify_arch_fallback():
    meta = {"qualify_arch": True}
    assert compute_own_hash_arch(meta, ["release", "gcc13"], "slc7_x86-64") \
        == compute_combined_arch(meta, ["release", "gcc13"], "slc7_x86-64")


def test_effective_arch_own_hash_returns_neutral():
    spec = {"own_hash": True, "_own_hash_arch": "x86_64-el9-gcc15"}
    assert effective_arch(spec, "x86_64-el9-gcc15-opt") == "x86_64-el9-gcc15"


def test_effective_arch_share_still_wins():
    spec = {"architecture": SHARED_ARCH, "_own_hash_arch": "x86_64-el9-gcc15"}
    assert effective_arch(spec, "x86_64-el9-gcc15-opt") == SHARED_ARCH


def test_effective_arch_plain_unchanged():
    assert effective_arch({}, "x86_64-el9-gcc15-opt") == "x86_64-el9-gcc15-opt"


def test_effective_arch_own_hash_without_stash_is_full():
    assert effective_arch({"own_hash": True}, "x86_64-el9-gcc15-opt") \
        == "x86_64-el9-gcc15-opt"


def _write(d, name, body):
    with open(os.path.join(d, "defaults-%s.sh" % name), "w") as f:
        f.write(body)


def test_readdefaults_collects_own_hash_neutral():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "gcc15", "package: defaults-gcc15\nversion: v1\nappend_arch: -gcc15\n---\n")
        _write(d, "opt", "package: defaults-opt\nversion: v1\nappend_arch: -opt\nown_hash_neutral: true\n---\n")
        errs = []
        meta, _body = readDefaults(d, ["gcc15", "opt"], errs.append, "x86_64-el9")
        assert not errs
        assert meta["_append_arch_qualifiers"] == ["-gcc15", "-opt"]
        assert meta["_own_hash_drop_qualifiers"] == ["-opt"]
        assert "own_hash_neutral" not in meta
        assert compute_own_hash_arch(meta, ["gcc15", "opt"], "x86_64-el9") == "x86_64-el9-gcc15"
        assert compute_combined_arch(meta, ["gcc15", "opt"], "x86_64-el9") == "x86_64-el9-gcc15-opt"


def test_readdefaults_no_marker_no_drop_list():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "gcc15", "package: defaults-gcc15\nversion: v1\nappend_arch: -gcc15\n---\n")
        errs = []
        meta, _body = readDefaults(d, ["gcc15"], errs.append, "x86_64-el9")
        assert not errs
        assert "_own_hash_drop_qualifiers" not in meta
