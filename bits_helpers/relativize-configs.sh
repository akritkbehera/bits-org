#!/bin/bash -e
# relativize-configs.sh <root>
#
# Rewrite absolute install paths baked into pkg-config (.pc), CMake package
# config (.cmake) and autotools *-config scripts under <root> to self-relative
# references, so the files stay correct wherever the package is laid down — a
# fresh install, a relocated CVMFS publish, or a reused store tarball that
# bypasses relocate-me.sh. .pc anchors on ${pcfiledir}, .cmake on
# ${CMAKE_CURRENT_LIST_DIR}, and a bin/*-config script recomputes its prefix
# from $0. Idempotent: a file that no longer contains the absolute prefix is
# skipped, so a second run is a no-op.
#
# Factored out of build_template.sh so the build and the reuse paths share one
# implementation. As a standalone script it is NOT run through the Python
# %-template that formats build_template.sh, so its %/${}/backticks are literal.
#
# PORTABLE: bits runs on macOS (BSD sed/awk) and Linux (GNU sed/awk). In-place
# editing uses the `sed -i.suffix … ; rm -f …suffix` form (as relocate-me.sh
# does), the only spelling that works on both — bare `sed -i "s|…"` treats the
# script as a backup suffix on BSD and corrupts the file. The *-config pass uses
# awk (POSIX, BSD+GNU) so the $()/&& prefix idiom needs no sed replacement-
# metacharacter escaping, and it overwrites the original only when awk succeeded
# with output, so a failed rewrite can never truncate the file.
#
# Known-prefix only: we replace this package's own <root> string (== $INSTALLROOT
# at build time), so a dependency's absolute path (a different INSTALLROOT hash)
# is never touched. Stale foreign-node tarballs are handled by rebuilding, not by
# pattern-matching an unknown prefix.

set -e

_absroot="${1:?usage: relativize-configs.sh <root>}"
_absroot="${_absroot%/}"          # tolerate a trailing slash; match with none
cd "$_absroot"

find . \( -name '*.pc' -o -name '*.cmake' \) -type f | while IFS= read -r _cf; do
  grep -qF "$_absroot" "$_cf" || continue
  case "$_cf" in
    *.pc) _anchor='${pcfiledir}' ;;
    *)    _anchor='${CMAKE_CURRENT_LIST_DIR}' ;;
  esac
  _dir="$(dirname "${_cf#./}")"
  if [ "$_dir" = "." ]; then
    _rel="$_anchor"
  else
    _up=""; _oIFS="$IFS"; IFS=/; for _c in $_dir; do _up="../$_up"; done; IFS="$_oIFS"
    _rel="${_anchor}/${_up%/}"
  fi
  sed -i.bits-reloc -e "s|$_absroot|$_rel|g" "$_cf"
  rm -f "${_cf}.bits-reloc"
done

# bin/*-config scripts (curl-config, xml2-config, …): everything they emit
# derives from prefix=, so rewrite the prefix/exec_prefix assignment of our own
# root to a $0-relative computation and repoint any remaining literal own-root at
# ${prefix}. Two passes over the file: pass 1 confirms the file assigns
# prefix (or exec_prefix) = our root, so ${prefix} is defined after the rewrite;
# if it does not, the file is left untouched (and flagged) rather than emitting
# an undefined ${prefix}. grep -IqF skips a binary *-config and matches literally;
# tmp-then-overwrite keeps the +x bit and only replaces the file on awk success.
_selfprefix='prefix=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)'
find . -path '*/bin/*-config' -type f | while IFS= read -r _sc; do
  grep -IqF "$_absroot" "$_sc" || continue
  if awk -v root="$_absroot" -v self="$_selfprefix" '
    function strip(s){ sub(/[ \t\r]+$/,"",s); sub(/^"/,"",s); sub(/"$/,"",s); return s }
    FNR==NR {
      if ($0 ~ /^prefix=/)      { v=$0; sub(/^prefix=/,"",v);      if (strip(v)==root) have=1 }
      if ($0 ~ /^exec_prefix=/) { v=$0; sub(/^exec_prefix=/,"",v); if (strip(v)==root) have=1 }
      next
    }
    !have { print; next }
    {
      if ($0 ~ /^prefix=/)      { v=$0; sub(/^prefix=/,"",v);      if (strip(v)==root) { print self;                  next } }
      if ($0 ~ /^exec_prefix=/) { v=$0; sub(/^exec_prefix=/,"",v); if (strip(v)==root) { print "exec_prefix=${prefix}"; next } }
      n=index($0, root)
      while (n>0) { $0=substr($0,1,n-1) "${prefix}" substr($0,n+length(root)); n=index($0, root) }
      print
    }' "$_sc" "$_sc" > "${_sc}.bits-reloc" && [ -s "${_sc}.bits-reloc" ]; then
    cat "${_sc}.bits-reloc" > "$_sc"
  fi
  rm -f "${_sc}.bits-reloc"
  grep -IqF "$_absroot" "$_sc" && echo "bits: relativize-configs: $_sc keeps an absolute prefix (no prefix= line to anchor)" >&2 || true
done

unset _absroot _cf _anchor _dir _up _c _oIFS _rel _selfprefix _sc
