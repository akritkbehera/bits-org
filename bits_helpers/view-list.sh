#!/bin/bash -e
# view-list.sh <root>
#
# Write <root>/.bits-view.json: the package's entries for a release's merged
# view, as package-relative paths with their kind (file | dir | link) and, for
# links, the target. Unfiltered on purpose — the recipe's `view:` rules are
# presentation only (not hashed) and are applied at publish time, so a reused
# tarball's list stays valid when they change. Per-package metadata that would
# collide in every view (etc/profile.d, etc/modulefiles, .meta.json, ...) is left out.
#
# Run from build_template.sh after the last change to the tree, before packing.
# As a standalone script it is not %-formatted. Sorted (LC_ALL=C) so the tarball
# stays byte-reproducible across nodes. Portable (BSD/GNU): no find -printf, and
# no subshell per entry (a large package has tens of thousands).

set -eo pipefail
root=$1
out="$root/.bits-view.json"
{
  printf '{"version": 1, "entries": ['
  ( cd "$root" && find . -mindepth 1 \( -path ./etc/profile.d -o -path ./etc/modulefiles \) -prune -o -print ) \
    | LC_ALL=C sort | {
    sep=
    while IFS= read -r p; do
      p=${p#./}
      case "$p" in
        .bits-view.json|.bits-view.json.tmp|.meta.json|.build-hash|relocate-me.sh|*.unrelocated) continue ;;
      esac
      t=
      if [ -L "$root/$p" ]; then k=link; t=$(readlink "$root/$p")
      elif [ -d "$root/$p" ]; then k=dir
      else k=file; fi
      e=${p//\\/\\\\}; e=${e//\"/\\\"}
      t=${t//\\/\\\\}; t=${t//\"/\\\"}
      printf '%s\n["%s","%s","%s"]' "$sep" "$e" "$k" "$t"
      sep=,
    done
  }
  printf '\n]}\n'
} > "$out.tmp"
mv "$out.tmp" "$out"
