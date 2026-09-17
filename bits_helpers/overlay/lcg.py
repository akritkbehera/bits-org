#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""``bits lcg-view`` — emit an lcgcmake-style LCG release view over a built bits
closure, so ATLAS's ``find_package(LCG <n> EXACT)`` resolves against the bits
install tree instead of an lcgcmake release.

Runs POST-build: it scans the installed packages under ``<work-dir>/<arch>`` and
reads each package's ``.meta.json`` (authoritative name/version/revision/hash +
direct runtime deps + the recorded CVMFS templates), then writes under ``<out>``::

    LCG_<num><postfix>/LCG_externals_<platform>.txt
    LCG_<num><postfix>/LCG_generators_<platform>.txt

Each externals line is ``name;hash;version;dir;deps``. AtlasLCG (LCGConfig.cmake)
uses fields 0-3 (name/id/version/dir) and sets ``<NAME>_LCGROOT`` from ``dir``.
``lcg_setup_release`` iterates the components ``externals;generators`` and sets
``LCG_FOUND=false`` if either file is MISSING, so the generators file is always
written (currently empty — every LCGROOT is set from the externals file; a proper
externals/generators split and the ``COMPILER:`` line, which AtlasLCG does not
consume, are later refinements).

``dir`` sources:
  * default (local view): the absolute LOCAL install prefix — machine/CWD-bound,
    for the pre-publish, build-from-cache case.
  * ``--cvmfs``: the package's CVMFS publish path, expanded from the
    ``cvmfs_templates`` recorded in its ``.meta.json`` (the same template
    ``bits cvmfs-path`` resolves), so a *published* find_package(LCG) resolves
    against CVMFS. Note the CVMFS template's ``{platform}`` segment is the bits
    arch (``--architecture``), not the LCG platform string in the manifest
    filename (``--platform``).

Wiring: dispatched early in the ``bits`` entry script (like ``preload``/``cvmfs``).

NOTE (verify on a real built tree): ``.meta.json`` is assumed to live at the
install-prefix root (``<work-dir>/<arch>/<pkg>/<ver>-<rev>/.meta.json``); and the
``--cvmfs`` expansion assumes each meta records ``cvmfs_templates.path`` (with
``{release}`` already baked) and ``cvmfs_templates.prefix``. Confirm both against
a real build-host ``.meta.json`` and adjust if they differ.
"""

import argparse
import glob
import json
import os
import sys

from bits_helpers.view import build_view, view_env

DESCRIPTION = "LCG release view: LCG_externals manifest + merged setup.sh over the built closure"

# Field/line delimiters the manifest and its CMake consumer (list semantics)
# reserve; a value carrying one would silently shift every subsequent list(GET).
_FORBIDDEN = (";", "\n", "\r")


def _load_meta(meta_path):
    with open(meta_path, encoding="utf-8") as handle:
        return json.load(handle)


def collect(work_dir, arch):
    """Scan ``<work_dir>/<arch>`` for installed packages.

    Returns ``(records, warnings, errors)``:
      * records  — dict name -> (install_dir, meta); newest ``.meta.json`` wins
        on duplicate package names.
      * warnings — non-fatal notes (duplicate names shadowed).
      * errors   — unreadable/invalid meta files. FATAL: a dropped package is a
        missing node in the closure, so the caller must not write a partial view.
    """
    root = os.path.join(work_dir, arch)
    chosen = {}          # name -> (install_dir, meta, mtime)
    warnings = []
    errors = []
    for meta_path in sorted(glob.glob(os.path.join(root, "*", "*", ".meta.json"))):
        try:
            meta = _load_meta(meta_path)
            mtime = os.path.getmtime(meta_path)
        except (OSError, ValueError) as exc:
            errors.append("%s: %s" % (meta_path, exc))
            continue
        pkg = meta.get("package") or {}
        name, version = pkg.get("name"), pkg.get("version")
        if not name or not version:
            errors.append("%s: .meta.json has no package name/version" % meta_path)
            continue
        install_dir = os.path.dirname(meta_path)
        prev = chosen.get(name)
        if prev is None or mtime > prev[2]:
            if prev is not None:
                warnings.append("duplicate package %r: using %s, ignoring %s"
                                % (name, install_dir, prev[0]))
            chosen[name] = (install_dir, meta, mtime)
        else:
            warnings.append("duplicate package %r: using %s, ignoring %s"
                            % (name, prev[0], install_dir))
    return {n: (v[0], v[1]) for n, v in chosen.items()}, warnings, errors


def _expand_template(template, subst):
    """Curly-brace token expansion, matching cvmfs_path._expand."""
    for key, value in subst.items():
        template = template.replace("{%s}" % key, value)
    return template


def resolve_dir(meta, install_dir, arch, cvmfs, cvmfs_prefix):
    """The ``dir`` (LCGROOT) field for one package: local abspath, or the CVMFS
    publish path from the recorded templates when ``cvmfs`` is set."""
    if not cvmfs:
        return os.path.abspath(install_dir)
    pkg = meta["package"]
    templates = meta.get("cvmfs_templates") or {}
    template = templates.get("path")
    if not template:
        raise ValueError(
            "package %r: --cvmfs requested but .meta.json records no "
            "cvmfs_templates.path (this build was not CVMFS-destined)" % pkg["name"])
    prefix = (cvmfs_prefix or templates.get("prefix") or "").rstrip("/")
    if not prefix:
        raise ValueError(
            "package %r: no CVMFS prefix (.meta.json has no cvmfs_templates.prefix "
            "and no --cvmfs-prefix given)" % pkg["name"])
    subst = {
        "prefix": prefix,
        "pkg": pkg["name"],
        "tag": pkg["version"],
        "version": pkg["version"],
        "platform": arch,              # CVMFS {platform} segment is the bits arch
        "family": "",                  # per-package; templates use {family}{pkg}
        "revision": str(pkg.get("revision", "")),
        "commit": "",
        "install_dir": "",
        "user": "",
    }
    resolved = _expand_template(template, subst)
    if "{" in resolved or "}" in resolved:
        raise ValueError(
            "package %r: unresolved placeholder in CVMFS path %r — e.g. {release} "
            "was not baked into the .meta.json" % (pkg["name"], resolved))
    return resolved


def manifest_line(name, dir_path, meta):
    """Return one ``name;hash;version;dir;deps`` line. Raises ValueError if any
    delimiter-reserved character would corrupt the manifest."""
    pkg = meta["package"]
    version = pkg["version"]
    pkg_hash = pkg.get("hash", "")
    for label, value in (("name", name), ("version", version),
                         ("hash", pkg_hash), ("dir", dir_path)):
        if any(ch in str(value) for ch in _FORBIDDEN):
            raise ValueError(
                "package %r: %s %r contains ';' or a newline — cannot encode it "
                "into the manifest" % (name, label, value))
    runtime = (meta.get("dependencies") or {}).get("direct", {}).get("runtime") or []
    dep_tokens = []
    for dep in runtime:
        dep_name = dep.get("name")
        if not dep_name:
            continue
        dep_ver = dep.get("version")
        dep_tokens.append("%s-%s" % (dep_name, dep_ver) if dep_ver else dep_name)
    return "%s;%s;%s;%s;%s" % (name, pkg_hash, version, dir_path, ",".join(dep_tokens))


def _atomic_write(path, text):
    """Temp file + os.replace so a reader never sees a truncated manifest and an
    interrupted run leaves the previous file intact."""
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bits overlay lcg",
        description="Emit an lcgcmake LCG release view over a built bits closure.")
    parser.add_argument("-a", "--architecture", required=True,
                        help="bits arch subtree under <work-dir> (e.g. x86_64-el9-gcc15).")
    parser.add_argument("-w", "--work-dir", dest="work_dir",
                        default=os.environ.get("BITS_WORK_DIR", "sw"),
                        help="bits work dir holding the install tree (default: %(default)s).")
    parser.add_argument("--platform", required=True,
                        help="LCG platform string for the manifest FILENAME "
                             "(e.g. x86_64-el9-gcc15-opt).")
    parser.add_argument("--version-number", dest="version_number", required=True,
                        help="LCG version number for the release dir (e.g. 110).")
    parser.add_argument("--postfix", default="",
                        help="LCG version postfix (e.g. _ATLAS_5). Default: none.")
    parser.add_argument("--out", default=".",
                        help="LCG_RELEASE_BASE root to write LCG_<num><postfix>/ under "
                             "(default: current directory).")
    parser.add_argument("--cvmfs", action="store_true",
                        help="Emit CVMFS publish paths (from each .meta.json's "
                             "cvmfs_templates) instead of local install dirs.")
    parser.add_argument("--cvmfs-prefix", dest="cvmfs_prefix", default="",
                        help="Override the CVMFS prefix ({prefix}) used with --cvmfs "
                             "(default: the prefix recorded in each .meta.json).")
    parser.add_argument("--build-view", dest="build_view", default="",
                        help="Also materialise the merged symlink-farm view over the "
                             "scanned closure into this directory, with a setup.sh that "
                             "collapses PATH/LD_LIBRARY_PATH/... onto it (native "
                             "bits_helpers.view — no lcgcmake create_lcg_view needed).")
    parser.add_argument("--lib-path-var", dest="lib_path_var", default="LD_LIBRARY_PATH",
                        help="Loader path variable for the view setup.sh "
                             "(DYLD_LIBRARY_PATH on macOS). Default: %(default)s.")
    args = parser.parse_args(argv)

    records, warnings, errors = collect(args.work_dir, args.architecture)
    for warning in warnings:
        sys.stderr.write("lcg-view: warning: %s\n" % warning)
    if errors:
        for err in errors:
            sys.stderr.write("lcg-view: error: %s\n" % err)
        sys.stderr.write("lcg-view: refusing to write a partial view (%d unreadable "
                         ".meta.json) — the closure would be incomplete.\n" % len(errors))
        return 1
    if not records:
        sys.stderr.write("lcg-view: no installed packages with .meta.json under %s/%s\n"
                         % (args.work_dir, args.architecture))
        return 1

    lines = []
    try:
        for name, (install_dir, meta) in records.items():
            dir_path = resolve_dir(meta, install_dir, args.architecture,
                                   args.cvmfs, args.cvmfs_prefix)
            lines.append(manifest_line(name, dir_path, meta))
    except ValueError as exc:
        sys.stderr.write("lcg-view: error: %s\n" % exc)
        return 1
    lines.sort()

    release = "LCG_%s%s" % (args.version_number, args.postfix)
    dest = os.path.join(args.out, release)
    externals = os.path.join(dest, "LCG_externals_%s.txt" % args.platform)
    generators = os.path.join(dest, "LCG_generators_%s.txt" % args.platform)
    try:
        os.makedirs(dest, exist_ok=True)
        _atomic_write(externals, "\n".join(lines) + "\n")
        _atomic_write(generators,
                      "# Generators are emitted into LCG_externals_%s.txt for now.\n"
                      "# Kept present so find_package(LCG) keeps LCG_FOUND true.\n"
                      % args.platform)
    except OSError as exc:
        sys.stderr.write("lcg-view: error: could not write the view under %s: %s\n"
                         % (dest, exc))
        return 1

    sys.stderr.write("lcg-view: wrote %d packages to %s%s\n"
                     % (len(lines), externals, " (CVMFS paths)" if args.cvmfs else ""))

    if args.build_view:
        rc = _build_view_and_setup(records, args.build_view, args.lib_path_var)
        if rc:
            return rc

    print(externals)
    return 0


def _build_view_and_setup(records, view_dir, lib_path_var):
    """Materialise the merged view over the scanned closure and write setup.sh.

    Uses the native bits view primitives (build_view + view_env): the symlink
    farm collapses PATH/LD_LIBRARY_PATH/CMAKE_PREFIX_PATH/PKG_CONFIG_PATH/
    PYTHONPATH to one entry each, exactly like an lcgcmake LCG view, without
    vendoring create_lcg_view.py."""
    # Local install prefixes, sorted for determinism (conflicts are reported).
    roots = sorted(os.path.abspath(install_dir) for install_dir, _ in records.values())
    try:
        res = build_view(roots, view_dir)
    except OSError as exc:
        sys.stderr.write("lcg-view: error: could not build the view under %s: %s\n"
                         % (view_dir, exc))
        return 1
    for path, winner, loser in res.get("conflicts", []):
        sys.stderr.write("lcg-view: view conflict on %s: kept %s, dropped %s\n"
                         % (path, winner, loser))
    # Detect the Python site-packages minor version from the merged tree.
    python_mm = None
    for _libdir in ("lib", "lib64"):
        for site in sorted(glob.glob(os.path.join(view_dir, _libdir, "python*", "site-packages"))):
            m = os.path.basename(os.path.dirname(site))  # pythonX.Y
            python_mm = m[len("python"):] or None
            break
        if python_mm:
            break
    env = view_env(view_dir, lib_path_var=lib_path_var, python_mm=python_mm)
    # setup.sh PREPENDS the view's single entries to any inherited value.
    setup = os.path.join(view_dir, "setup.sh")
    def _sh_squote(val):
        # single-quoted literal: close-quote, escaped-quote, reopen for each '
        return "'" + val.replace("'", "'\\''") + "'"
    body = ["#!/bin/bash",
            "# Auto-generated by `bits overlay lcg --build-view`: collapse the release",
            "# environment onto this merged view. Source it (after setupViews.sh).",
            "export LCG_VIEW=%s" % _sh_squote(os.path.abspath(view_dir))]
    for var in sorted(env):
        # single-quote the value; the ${VAR:+:$VAR} prepend suffix stays outside
        body.append("export %s=%s${%s:+:$%s}" % (var, _sh_squote(env[var]), var, var))
    _atomic_write(setup, "\n".join(body) + "\n")
    os.chmod(setup, 0o755)
    sys.stderr.write("lcg-view: built view (%d links) + setup.sh at %s\n"
                     % (len(res.get("linked", [])), view_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
