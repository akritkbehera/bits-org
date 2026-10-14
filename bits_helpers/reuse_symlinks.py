# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local views of reused packages: linked payload, private initialization files."""

import hashlib
import json
import os
from pathlib import Path
import re
from shlex import quote
from shlex import split
import shutil
import stat
import subprocess
import tempfile

from bits_helpers.arch import effective_arch
from bits_helpers.utilities import pkg_to_shell_id


def _run_checked(command):
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError("Reference package setup failed: %s" % command[0]) from exc


def serialize_relocation_table(replacements):
    """Serialize mappings for relocate-references.sh without shell evaluation."""
    rows = []
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    for source, destination in ordered:
        if any(c in source or c in destination for c in ("\t", "\n")):
            raise ValueError("--symlinks cannot relocate paths containing tabs or newlines")
        rows.append(source + "\t" + destination)
    return "\n".join(rows)


def _relocate_references(root, replacements):
    script = Path(__file__).with_name("relocate-references.sh")
    _run_checked(["bash", str(script), str(root), serialize_relocation_table(replacements)])


def _existing_layout_matches(existing, staged, source, relative=Path()):
    """True when every existing entry is a compatible subset of a stage.

    Reuse the caller's already-created source symlinks, including a whole-package
    symlink, by replacing only the local directory entry with our prepared tree.
    Any local regular files must match the staged copies; foreign links/data fail
    closed. Symlink targets are compared after resolving, never followed for edit.
    """
    if existing.is_symlink():
        try:
            actual = existing.resolve(strict=True)
        except OSError:
            return False
        try:
            original = (source / relative).resolve(strict=True)
        except OSError:
            return False
        if actual != staged.resolve() and actual != original:
            return False
        return ((staged.is_dir() and actual.is_dir()) or (staged.is_file() and actual.is_file()))
    if staged.is_symlink():
        return False
    if existing.is_dir():
        if not staged.is_dir():
            return False
        return all((staged / item.name).exists() or (staged / item.name).is_symlink()
                   for item in existing.iterdir()) and all(
                       _existing_layout_matches(item, staged / item.name, source,
                                                relative / item.name)
                       for item in existing.iterdir())
    if not existing.is_file() or not staged.is_file():
        return False
    try:
        return existing.read_bytes() == staged.read_bytes()
    except OSError:
        return False


def _install_stage(staged, destination, source):
    """Install a prepared package, preserving a rollback copy if it exists."""
    if not os.path.lexists(destination):
        staged.rename(destination)
        return None
    if not _existing_layout_matches(destination, staged, source):
        raise ValueError("--symlinks found incompatible existing content at %s" % destination)
    backup = Path(tempfile.mkdtemp(prefix=".reuse-old-", dir=str(destination.parent)))
    old = backup / "package"
    destination.rename(old)
    try:
        staged.rename(destination)
    except BaseException:
        try:
            old.rename(destination)
        except BaseException:
            # Keep the old tree in its backup location if rollback itself fails.
            raise
        shutil.rmtree(backup)
        raise
    return backup


def stage_reused_package(spec, install_base, work_dir, architecture,
                         runtime_work_dir=None):
    """Stage one selected module under work_dir without writing to its source.

    Directories containing private files are real directories; the other entries
    are symlinks. No relocation program is run on a linked tree, since it could
    edit the deployment. Publication of consumers still requires their dependency
    closure at the destination. Config files inside linked lib/bin remain as-is.
    """
    base = Path(install_base).absolute()
    work = Path(work_dir).absolute()
    runtime = Path(runtime_work_dir or work).absolute()
    arch = effective_arch(spec, architecture)
    package, verrev = spec["reuse_module_id"].split("/", 1)
    family = spec.get("pkg_family", "")
    for segment in (package, verrev, arch, family):
        if segment and (segment in (".", "..") or "/" in segment):
            raise ValueError("Invalid reused package path segment: %r" % segment)
    suffix = Path(family) / package / verrev if family else Path(package) / verrev
    candidates = [base / suffix, base / package / verrev]
    source = next((p for p in candidates
                   if (p / "etc/profile.d/init.sh").is_file()), None)
    if source is None:
        raise ValueError("--symlinks needs the deployed init.sh for %s under %s"
                         % (spec["reuse_module_id"], base))
    destination = work / arch / suffix
    local_root = runtime / arch / suffix
    parent = destination.parent
    while parent != work:
        if parent.is_symlink():
            raise ValueError("--symlinks refuses a linked destination parent: %s" % parent)
        parent = parent.parent
    if destination.absolute() == source.absolute():
        raise ValueError("--symlinks source and destination are the same: %s" % source)

    original = (source / "etc/profile.d/init.sh").read_text()
    # Longest first: the flat deployment and the local family layout may differ.
    replacements = {str(source): str(local_root),
                    str(base): str(runtime / arch)}
    # Older init.sh files default WORK_DIR to their original build workdir.
    # Read the literal PKG_DIR without executing the deployment's shell code.
    pkginfo = source / "etc/profile.d/.bits-pkginfo"
    if pkginfo.is_file():
        for line in pkginfo.read_text().splitlines():
            if line.startswith("PKG_DIR="):
                value = split(line[len("PKG_DIR="):])
                if len(value) == 1 and os.path.isabs(value[0]) and value[0] != "/":
                    replacements.setdefault(value[0], str(runtime))
    # Consumers can inherit reference paths from linked .pc/.la files or
    # compiler wrappers. Carry these mappings to their post-install rewrite.
    # Include the physical root in case a tool resolves our source symlink.
    replacements.setdefault(str(source.resolve()), str(local_root))
    spec["reuse_reference_paths"] = dict(replacements)
    pattern = re.compile("|".join(
        re.escape(p) for p in sorted(replacements, key=len, reverse=True)))
    relocated = pattern.sub(lambda m: replacements[m.group()], original)
    # A consumer can have a different effective architecture (share/toolchain).
    # Keep WORK_DIR at the consumer's local root and scope BITS_ARCH_PREFIX to
    # this package while sourcing. Unique names also allow nested dependency init.
    saved = "_bits_reuse_arch_" + pkg_to_shell_id(package)
    init = ('if [ -z "${WORK_DIR:-}" ]; then WORK_DIR=%s; fi\n'
            '%s="${BITS_ARCH_PREFIX-}"; %s_set="${BITS_ARCH_PREFIX+x}"\n'
            'BITS_ARCH_PREFIX=%s\n' % (quote(str(runtime)), saved, saved, quote(arch)))
    init += relocated.rstrip() + "\n"
    init += ('if [ -n "${%s_set}" ]; then BITS_ARCH_PREFIX="${%s}"; '
             'else unset BITS_ARCH_PREFIX; fi\nunset %s %s_set\n'
             % (saved, saved, saved, saved))

    identity = {"source": str(source.resolve()), "layout_version": 2,
                "init_sha256": hashlib.sha256(init.encode()).hexdigest()}
    marker = ".bits-reuse-symlinks.json"
    # Keep an already completed stage as-is.
    if os.path.lexists(destination):
        if not destination.is_symlink() and (destination / marker).is_file():
            if json.loads((destination / marker).read_text()) == identity:
                local_init = destination / "etc/profile.d/init.sh"
                private = all((not (destination / "etc").is_symlink(),
                               not local_init.parent.is_symlink(),
                               not local_init.is_symlink(), local_init.is_file()))
                if private and local_init.read_text() == init:
                    return str(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".reuse-", dir=str(destination.parent)))
    try:
        scram_project = (source / ".SCRAM").is_dir()
        for entry in source.iterdir():
            target = staged / entry.name
            if entry.name == "etc" and (entry / "profile.d").exists():
                target.mkdir()
                for child in entry.iterdir():
                    copy = child.name == "scram.d" or (
                        child.name == "profile.d" and (child / "init.sh").exists())
                    if copy:
                        shutil.copytree(child, target / child.name, symlinks=True)
                    else:
                        (target / child.name).symlink_to(child)
            elif any((entry.name == "tools" and (entry / "selected").is_dir(),
                      scram_project and entry.name in (".SCRAM", "config"))):
                shutil.copytree(entry, target, symlinks=True)
            elif entry.name != marker:
                target.symlink_to(entry)

        # CMS makes copied regular files writable. Do not traverse any links.
        writable = []
        for directory, dirs, files in os.walk(staged, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
            for name in files:
                path = Path(directory) / name
                if stat.S_ISREG(path.lstat().st_mode):
                    writable.append(str(path))
        for start in range(0, len(writable), 128):
            _run_checked(["chmod", "+w"] + writable[start:start + 128])
        # Preserve bits' WORK_DIR/BITS_ARCH_PREFIX setup in its local init.sh.
        # Relocate other copied profile/SCRAM/tool files with the same rule.

        def write_init(root):
            path = root / "etc/profile.d/init.sh"
            if path.is_symlink():
                path.unlink()
            path.write_text(init)

        if scram_project:
            for name in (".SCRAM", "config"):
                _run_checked(["chmod", "-R", "+w", str(staged / name)])
            # Run at the final package location, as REFERENCE_PACKAGE_POST does.
            backup = _install_stage(staged, destination, source)
            refroot = base.parent if base.name == arch else base
            try:
                _run_checked([str(destination / "config/SCRAM/projectAreaRename.pl"),
                              str(refroot), str(runtime), architecture, str(destination)])
                # CMS performs the text substitution after projectAreaRename.
                _relocate_references(destination, replacements)
                write_init(destination)
                (destination / marker).write_text(json.dumps(identity, sort_keys=True) + "\n")
            except BaseException:
                if destination.exists() and not destination.is_symlink():
                    shutil.rmtree(destination)
                if backup is not None:
                    (backup / "package").rename(destination)
                    shutil.rmtree(backup)
                raise
            if backup is not None:
                shutil.rmtree(backup)
            return str(destination)
        _relocate_references(staged, replacements)
        write_init(staged)
        (staged / marker).write_text(json.dumps(identity, sort_keys=True) + "\n")
        backup = _install_stage(staged, destination, source)
        if backup is not None:
            shutil.rmtree(backup)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return str(destination)
