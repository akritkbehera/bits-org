# SPDX-FileCopyrightText: 2015-2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""External checksum store for bits packages.

Each recipe repository can carry an optional ``checksums/`` subdirectory.
A file named ``checksums/<pkgname>.checksum`` (case-insensitive package name)
supplies checksums for that package's sources and patches, and optionally pins
the expected git commit SHA for the ``source:`` + ``tag:`` checkout.

File format (YAML)
------------------

::

    # checksums/mylib.checksum
    # Re-generate with:  bits checksums --write mylib

    commits:                  # git tag -> pinned commit SHA
      v1.0: abc123def456abc123def456abc123def456abc1


    sources:
      https://example.com/mylib-1.0.tar.gz: sha256:e3b0c44298fc1c149afb...
      https://example.com/extra.tar.bz2:    sha512:cf83e1357eefb8bdf154...

    patches:
      fix-endian.patch:          sha256:a665a45920422f9d417e4867efdc4fb8...
      add-missing-header.patch:  sha256:d41d8cd98f00b204e9800998ecf8427e...

All sections are optional.  Commit pins are bare SHAs (no ``algo:`` prefix)
because git always uses SHA-1 or SHA-256 for commit identities.  ``commits``
is keyed by the resolved ``tag:``, so pins for several tags (the recipe's own
and those a defaults profile overrides it to) coexist.  The legacy single
``tag: <sha>`` pin is still read, but applies only to the recipe's own
tag/version: a defaults override or version pin that changes them drops it.

A repository providing an active ``defaults-*.sh`` profile can carry
``checksums/<pkg>.checksum`` files too, for the sources its overrides
introduce; they are merged over the recipe repository's file (see
:func:`load_for_spec`).

Merge semantics
---------------

The external file *wins* over any inline checksum carried in the recipe's
``sources:`` or ``patches:`` entries.  If a URL or filename appears in the
external file, that checksum is used regardless of any comma-suffix in the
recipe.  If a URL / filename is **not** in the external file, the inline
comma-suffix (if present) is used as the fallback.

This makes the checksum file the single authoritative security artefact,
while keeping inline entries useful during development or for simple cases.
"""

import os
import re

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from bits_helpers.log import debug, warning

# Commit SHA: 40 hex chars (SHA-1) or 64 hex chars (SHA-256)
_COMMIT_RE = re.compile(r'^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$')

# ── Discovery ─────────────────────────────────────────────────────────────────

def find_checksum_file(pkgdir: str, pkgname: str):
    """Return the path to ``<pkgdir>/checksums/<pkgname>.checksum``, or ``None``.

    The lookup is case-insensitive (package name is lowercased before joining).
    """
    path = os.path.join(pkgdir, "checksums", pkgname.lower() + ".checksum")
    return path if os.path.isfile(path) else None


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_checksum_file(path: str) -> dict:
    """Parse a ``.checksum`` file and return a normalised dict::

        {
            "tag":     "<commit-sha>" | None,
            "commits": {"<tag>": "<commit-sha>", ...},
            "sources": {"<url>": "algo:hex", ...},
            "patches": {"<filename>": "algo:hex", ...},
        }

    Unknown keys are silently ignored so that future extensions are backward
    compatible.  Raises ``ValueError`` on YAML parse errors or invalid values.
    """
    with open(path, encoding="utf-8") as fh:
        return parse_checksum_text(fh.read(), path)


def parse_checksum_text(text: str, path: str = "<text>") -> dict:
    """:func:`parse_checksum_file` for the file content *text*."""
    if yaml is None:
        raise ImportError(
            "PyYAML is required to parse checksum files: pip install pyyaml"
        )

    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError("YAML parse error in %s: %s" % (path, exc)) from exc

    if not isinstance(data, dict):
        raise ValueError("Checksum file must be a YAML mapping: %s" % path)

    result = {"tag": None, "commits": {}, "sources": {}, "patches": {}}

    # --- tag (commit pin) ----------------------------------------------------
    raw_tag = data.get("tag")
    if raw_tag is not None:
        raw_tag = str(raw_tag).strip()
        if not _COMMIT_RE.match(raw_tag):
            raise ValueError(
                "Invalid commit SHA in %s — expected 40 or 64 hex chars, "
                "got: %r" % (path, raw_tag)
            )
        result["tag"] = raw_tag.lower()

    # --- commits (tag -> commit pin) -----------------------------------------
    raw_commits = data.get("commits") or {}
    if not isinstance(raw_commits, dict):
        raise ValueError("'commits' in %s must be a YAML mapping" % path)
    for tag, sha in raw_commits.items():
        sha = str(sha).strip()
        if not _COMMIT_RE.match(sha):
            raise ValueError("Invalid commit SHA for tag %r in %s: %r" % (tag, path, sha))
        result["commits"][str(tag).strip()] = sha.lower()

    # --- sources -------------------------------------------------------------
    raw_sources = data.get("sources") or {}
    if not isinstance(raw_sources, dict):
        raise ValueError("'sources' in %s must be a YAML mapping" % path)
    for url, cksum in raw_sources.items():
        result["sources"][str(url).strip()] = str(cksum).strip()

    # --- patches -------------------------------------------------------------
    raw_patches = data.get("patches") or {}
    if not isinstance(raw_patches, dict):
        raise ValueError("'patches' in %s must be a YAML mapping" % path)
    for fname, cksum in raw_patches.items():
        result["patches"][str(fname).strip()] = str(cksum).strip()

    debug("Loaded checksum store from %s: tag=%s, %d sources, %d patches",
          path, result["tag"], len(result["sources"]), len(result["patches"]))
    return result


def _empty_store() -> dict:
    return {"tag": None, "commits": {}, "sources": {}, "patches": {}}


def load_for_spec(spec: dict, extra_dirs=()) -> dict:
    """Discover and parse the checksum files for *spec*.

    The recipe repository's ``checksums/<pkg>.checksum`` comes first; the same
    file in each of *extra_dirs* (the repositories providing the active
    defaults profiles) is merged over it, later ones winning per key.  Their
    legacy ``tag:`` is ignored: it cannot say which tag it pins.

    Returns an empty store if no file is found, so callers never have to
    handle ``None``.  An unreadable file is warned about and skipped.
    """
    pkgname = spec.get("package", "")
    result = _empty_store()
    seen = set()
    for i, d in enumerate([spec.get("pkgdir", "")] + list(extra_dirs)):
        if not d or os.path.abspath(d) in seen:
            continue
        seen.add(os.path.abspath(d))
        path = find_checksum_file(d, pkgname)
        if path is None:
            continue
        try:
            store = parse_checksum_file(path)
        except (ValueError, IOError, OSError) as exc:
            warning("Could not load checksum file %s: %s", path, exc)
            continue
        if i == 0:
            result["tag"] = store["tag"]
        for key in ("commits", "sources", "patches"):
            result[key].update(store[key])
    return result


def merge_into_spec(spec: dict, store: dict, legacy_pin: bool = True) -> None:
    """Inject checksum store data into *spec* in-place.

    Sets:
    - ``spec["source_checksums"]``  — ``{url: "algo:hex", ...}``
    - ``spec["patch_checksums"]``   — ``{filename: "algo:hex", ...}``
    - ``spec["pin_commits"]``       — ``{tag: sha, ...}``
    - ``spec["pin_commit"]``        — legacy single SHA, or ``None``; dropped
      when *legacy_pin* is false (the tag/version was overridden)

    These keys are consumed by ``workarea.checkout_sources``.
    """
    spec["source_checksums"] = dict(store.get("sources") or {})
    spec["patch_checksums"] = dict(store.get("patches") or {})
    spec["pin_commits"] = dict(store.get("commits") or {})
    spec["pin_commit"] = store.get("tag") if legacy_pin else None


# ── Writing ───────────────────────────────────────────────────────────────────

def _yaml_key(key: str) -> str:
    """*key* as a YAML mapping key: plain when it round-trips, else quoted
    (a tag like ``1.10`` or ``on`` would otherwise parse as a float/bool)."""
    try:
        parsed = next(iter(yaml.safe_load("%s: x" % key)))
        if isinstance(parsed, str) and parsed == key:
            return key
    except Exception:  # noqa: BLE001 — anything odd gets quoted
        pass
    return '"%s"' % key.replace("\\", "\\\\").replace('"', '\\"')


def format_checksum_file(pkgname: str, store: dict) -> str:
    """Render *store* as a YAML ``.checksum`` file string.

    This is called by ``bits build --write-checksums`` to persist computed
    checksums back to the recipe repository.
    """
    lines = [
        "# checksums/%s.checksum" % pkgname.lower(),
        "# Re-generate with:  bits checksums --write %s" % pkgname,
        "",
    ]

    if store.get("tag"):
        lines += ["tag: %s" % store["tag"], ""]

    if store.get("commits"):
        lines.append("commits:")
        for tag, sha in sorted(store["commits"].items()):
            lines.append("  %s: %s" % (_yaml_key(tag), sha))
        lines.append("")

    if store.get("sources"):
        lines.append("sources:")
        for url, cksum in sorted(store["sources"].items()):
            lines.append("  %s: %s" % (_yaml_key(url), cksum))
        lines.append("")

    if store.get("patches"):
        lines.append("patches:")
        for fname, cksum in sorted(store["patches"].items()):
            lines.append("  %s: %s" % (_yaml_key(fname), cksum))
        lines.append("")

    return "\n".join(lines)


def write_checksum_file(pkgdir: str, pkgname: str, store: dict) -> str:
    """Write *store* to ``<pkgdir>/checksums/<pkgname>.checksum``.

    Creates the ``checksums/`` directory if it does not exist.
    Returns the path of the written file.
    """
    checksums_dir = os.path.join(pkgdir, "checksums")
    os.makedirs(checksums_dir, exist_ok=True)
    path = os.path.join(checksums_dir, pkgname.lower() + ".checksum")
    content = format_checksum_file(pkgname, store)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def _same_checksum(old: str, new: str) -> bool:
    """True unless *old* and *new* are the same algorithm with different digests
    (a different algorithm cannot be compared, so the existing entry stands)."""
    oa, _, od = old.partition(":")
    na, _, nd = new.partition(":")
    if not od or not nd:           # commit SHAs carry no algo: prefix
        return old.lower() == new.lower()
    return oa.lower() != na.lower() or od.lower() == nd.lower()


def _insert_entries(text: str, section: str, entries: dict) -> str:
    """*text* with ``  key: value`` lines for *entries* added after the last
    entry of the top-level *section* (a new section at the end if there is
    none), so that comments and hand formatting survive."""
    lines = text.splitlines()
    add = ["  %s: %s" % (_yaml_key(k), v) for k, v in sorted(entries.items())]
    head = re.compile(r"^%s:\s*(#.*)?$" % re.escape(section))
    start = next((i for i, line in enumerate(lines) if head.match(line)), None)
    if start is None and any(line.startswith(section + ":") for line in lines):
        raise ValueError("%s: not a block mapping" % section)   # e.g. `sources: {}`
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ([""] if lines else []) + [section + ":"] + add
    else:
        last = start
        for i in range(start + 1, len(lines)):
            if lines[i][:1] in (" ", "\t"):
                if lines[i].strip() and not lines[i].lstrip().startswith("#"):
                    last = i
            elif lines[i].strip():
                break                    # the next top-level key or comment
        lines[last + 1:last + 1] = add
    return "\n".join(lines) + "\n"


def update_checksum_file(pkgdir: str, pkgname: str, new: dict):
    """Merge *new* (``commits``/``sources``/``patches``) into
    ``<pkgdir>/checksums/<pkgname>.checksum``, keeping every existing entry
    and, where possible, the file's comments and layout.

    An existing entry that disagrees with *new* is never overwritten: it is
    returned in *conflicts* as ``(section, key, old, new)``.  Returns
    ``(path, conflicts)``; *path* is ``None`` when nothing was added.
    Raises ``ValueError`` if the existing file is invalid.
    """
    path = find_checksum_file(pkgdir, pkgname)
    merged = parse_checksum_file(path) if path else _empty_store()
    _old = {k: dict(merged[k]) for k in ("commits", "sources", "patches")}
    added, conflicts = False, []
    for section in ("commits", "sources", "patches"):
        for key, value in sorted((new.get(section) or {}).items()):
            value = str(value).strip()
            value = value.lower() if section == "commits" else value
            cur = merged[section].get(key)
            if cur is None:
                merged[section][key] = value
                added = True
            elif not _same_checksum(cur, value):
                conflicts.append((section, key, cur, value))
    if not added:
        return None, conflicts
    if path is None:
        return write_checksum_file(pkgdir, pkgname, merged), conflicts
    # Add the new lines to the existing text; if that does not parse back to
    # the merged store (an unusual layout, e.g. `sources: {}`), rewrite it.
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        for section in ("commits", "sources", "patches"):
            extra = {k: merged[section][k] for k in (new.get(section) or {})
                     if k not in _old[section]}
            if extra:
                text = _insert_entries(text, section, extra)
        ok = parse_checksum_text(text, path) == merged
    except ValueError:
        ok = False
    if not ok:
        return write_checksum_file(pkgdir, pkgname, merged), conflicts
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path, conflicts
