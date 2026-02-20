# `force_revision` Feature

## Problem

Bits auto-increments revision numbers (`1`, `2`, `local1`, ...) by scanning
existing tarballs. This is essential for remote sync — two different builds of
the same version need distinct tarball filenames so they don't collide on S3.
But it means the local install directory changes name on every rebuild
(`v1.3.1-1/`, then `v1.3.1-2/`, etc.), which is inconvenient when you want
a stable, predictable path.

`force_revision` lets you pin the local directory name while keeping the
auto-incremented revision for remote storage.

## Usage

In `defaults-release.sh` YAML:

```yaml
force_revision:
  Python: 1
  my-package: shared
```

This installs Python to `/sw/arch/Python/v3.11-1/` and my-package to
`/sw/arch/my-package/v1.0-shared/` regardless of how many times they're rebuilt.
The tarballs uploaded to S3 still use the bits-assigned revision
(e.g., `my-package-v1.0-3.arch.tar.gz`).

The empty string is also valid:

```yaml
force_revision:
  my-package: ""
```

This produces `/sw/arch/my-package/v1.0/` with no revision suffix at all.

## The Two Revisions

When `force_revision` is set, two revision values coexist for the same package:

**bits revision** (`spec["revision"]`): Auto-assigned by scanning tarballs in
`TARS/{arch}/{package}/`. Values like `"1"`, `"2"`, `"local1"`. Used for
everything that touches the remote store — tarball filenames, S3 keys, dist
symlink directories. This prevents naming collisions when multiple builds
upload to the same remote.

**force_revision** (`spec["force_revision"]`): The user-specified value from
defaults-release. Used for everything local — the install directory where files
live on disk, the paths in init.sh that other packages source, and the `latest`
symlinks.

The split happens at two clear boundaries:

- **build_template.sh**: `PKGREVISION` holds the bits revision (used for
  `PACKAGE_WITH_REV` tarball name). `INSTALL_REVISION` and `VERSION_REV` hold
  the force_revision (used for `PKGPATH` and all local directory operations).

- **build.py main loop**: `spec["revision"]` is the bits revision (passed as
  `PKGREVISION` env var, used in `createDistLinks`, passed to sync methods).
  `spec["force_revision"]` (falling back to `spec["revision"]`) is used for
  `hashPath`, symlink targets, and `generate_initdotsh`.

## What Uses Which

| bits revision (`spec["revision"]`) | force_revision |
|-|-|
| Tarball filename: `pkg-v1-1.arch.tar.gz` | Install dir: `/sw/arch/pkg/v1-shared/` |
| S3 store path: `TARS/arch/store/ab/hash/pkg-v1-1.arch.tar.gz` | `.build-hash` location: `/sw/arch/pkg/v1-shared/.build-hash` |
| Symlink in `TARS/arch/pkg/` | `latest` symlink target: `v1-shared` |
| Dist dirs: `TARS/arch/dist/pkg/pkg-v1-1/` | init.sh `_ROOT`: `$WORK_DIR/arch/pkg/v1-shared` |
| `PKGREVISION` env var in build script | `FORCED_REVISION` / `VERSION_REV` env vars |
| `SPECS/{arch}/pkg/v1-1/build.sh` path | `PKGPATH` in build template |

## Lifecycle of a Build with `force_revision`

### 1. Reading force_revision from defaults-release

`build.py:get_force_revision()` reads the `force_revision` mapping from
`defaults-release` and returns the value for the package if it exists.
The value is stored in `spec["force_revision"]` for the rest of the build.

### 2. Hash computation

`storeHashes()` includes `force_revision` in the package hash **only when the
key exists**. A package without `force_revision` produces the exact same hash
as before — no backward compatibility break. A package with
`force_revision: shared` gets a different hash than the same package with
`force_revision: test` or without `force_revision` at all.

### 3. Revision assignment (bits revision)

The main build loop in `doBuild` scans existing tarball symlinks in
`TARS/{arch}/{package}/` and picks the next free revision number, or reuses
an existing one if the hash matches. This is completely unchanged by
`force_revision` — the loop works with tarball filenames that use the bits
revision, and the remote store only sees bits revisions.

### 4. Build execution

`build_template.sh` receives both revisions as environment variables:

```bash
PKGREVISION=1              # bits revision, from spec["revision"]
FORCED_REVISION=shared     # only set when force_revision exists in defaults

INSTALL_REVISION="${FORCED_REVISION-$PKGREVISION}"   # = "shared"

# VERSION_REV: version with install revision for local paths
if [ -n "$INSTALL_REVISION" ]; then
  VERSION_REV="$PKGVERSION-$INSTALL_REVISION"        # = "v1.0-shared"
else
  VERSION_REV="$PKGVERSION"                          # = "v1.0"
fi

PKGPATH=$ARCHITECTURE/${PKGFAMILY_PREFIX}$PKGNAME/$VERSION_REV
#      = el9_amd64/my-package/v1.0-shared
```

The build recipe runs in `$INSTALLROOT` which is structured as
`INSTALLROOT/$PKGHASH/$PKGPATH`. After the build:

- **Tarball creation** uses `PKGREVISION` for the filename:
  `my-package-v1.0-1.arch.tar.gz`. This tarball's *internal* directory
  structure is `$PKGPATH` (which uses VERSION_REV).

- **rsync** copies from `INSTALLROOT/$PKGHASH/` to `$WORK_DIR`, placing files
  at `$WORK_DIR/$PKGPATH` = `$WORK_DIR/arch/my-package/v1.0-shared/`.

- **Relocation** runs `relocate-me.sh` from the VERSION_REV path.

- **latest symlinks** point to `v1.0-shared` (not `v1.0-1`).

- **`.build-hash`** is written at `$WORK_DIR/$PKGPATH/.build-hash`.

### 5. init.sh generation

`generate_initdotsh()` uses force_revision for dependency paths:

```bash
. "$WORK_DIR/$BITS_ARCH_PREFIX"/my-package/v1.0-shared/etc/profile.d/init.sh
```

And for the package's own `_ROOT`:

```bash
export MY_PACKAGE_ROOT=$WORK_DIR/$BITS_ARCH_PREFIX/my-package/v1.0-shared
```

When `force_revision` is empty string, the dash is omitted:

```bash
export MY_PACKAGE_ROOT=$WORK_DIR/$BITS_ARCH_PREFIX/my-package/v1.0
```

### 6. Upload to remote

`sync.py` methods use `spec["revision"]` (bits revision) for tarball names
and dist symlink paths. The remote store never sees the `force_revision`
value. `createDistLinks` also uses bits revision for the dist directory name.

### 7. Subsequent runs (cache hit)

On the next run, `build.py` checks `hashPath/.build-hash` where hashPath
uses the force_revision path. If the hash matches, the package is skipped
entirely — no tarball download, no build. `syncHelper.fetch_symlinks()` still
runs (to get current remote state for revision assignment), but
`syncHelper.fetch_tarball()` is never reached.

### 8. Cached tarball from remote

When a package hasn't been built locally but a matching tarball exists on the
remote:

1. `fetch_tarball()` downloads it to `TARS/{arch}/store/{hash[:2]}/{hash}/`
2. The tarball is passed as `CACHED_TARBALL` to `build_template.sh`
3. The script extracts it to a temp dir, then moves the version directory
   (which has VERSION_REV in its name, since it was built with the same
   `force_revision` — guaranteed by matching hash) to `$INSTALLROOT`
4. Relocation runs, `.build-hash` is written
5. On subsequent runs, the hashPath check skips the package

## The VERSION_REV Pattern

In `build_template.sh`, VERSION_REV is computed once and used for all local paths:

```bash
INSTALL_REVISION="${FORCED_REVISION-$PKGREVISION}"

if [ -n "$INSTALL_REVISION" ]; then
  VERSION_REV="$PKGVERSION-$INSTALL_REVISION"
else
  VERSION_REV="$PKGVERSION"
fi
```

- When INSTALL_REVISION is non-empty (e.g., `"shared"` or `"1"`): VERSION_REV is
  `v1.0-shared` or `v1.0-1`
- When INSTALL_REVISION is empty (`force_revision: ""`): VERSION_REV is `v1.0`
  (no dash, no suffix)

The same logic in Python uses a conditional expression:

```python
install_rev = spec["force_revision"] if spec.get("force_revision") is not None else spec["revision"]
version_rev = spec["version"] if install_rev == "" else "{}-{}".format(spec["version"], install_rev)
```

This is applied wherever a version-revision path is constructed: hashPath,
symlink targets, init.sh paths.
