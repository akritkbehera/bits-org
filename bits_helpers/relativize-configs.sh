#!/bin/bash -e
# relativize-configs.sh <root>
#
# Rewrite absolute install paths baked into pkg-config (.pc) and CMake package
# config (.cmake) files under <root> to self-relative anchors, so the files stay
# correct wherever the package is laid down — a fresh install, a relocated CVMFS
# publish, or a reused store tarball that bypasses relocate-me.sh. .pc anchors on
# ${pcfiledir}, .cmake on ${CMAKE_CURRENT_LIST_DIR}. Idempotent: a file that does
# not contain the absolute prefix is skipped, so a second run is a no-op.
#
# Factored out of build_template.sh so the build and the reuse paths share one
# implementation. As a standalone script it is NOT run through the Python
# %-template that formats build_template.sh, so its %/${}/backticks are literal.
#
# PORTABLE: bits runs on macOS (BSD sed) and Linux (GNU sed). In-place editing
# uses the `sed -i.suffix … ; rm -f …suffix` form (as relocate-me.sh does), which
# is the ONLY spelling that works on both — bare `sed -i "s|…"` treats the script
# as a backup suffix on BSD and corrupts the file.
#
# Mode 1 (default): strip the KNOWN <root> prefix (build-time call site, where the
# baked prefix equals $INSTALLROOT). Pattern mode for reused tarballs whose baked
# prefix is a foreign node's path is added in a later increment (--any-installroot).

set -e

_absroot="${1:?usage: relativize-configs.sh <root>}"
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
unset _absroot _cf _anchor _dir _up _c _oIFS _rel
