#!/bin/bash -e
THISDIR="$(cd -P "$(dirname "$0")" && pwd)"
source "${THISDIR}/etc/profile.d/.bits-pkginfo"
INSTALL_BASE=$(echo "$THISDIR" | sed "s|/$PP$||")

# Relocate files listed in .bits-relocate
if [[ -s "${THISDIR}/etc/profile.d/.bits-relocate" ]]; then
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    if [[ -f "${THISDIR}/$f" ]]; then
      sed -i.unrelocated \
        -e "s|${PKG_DIR}/INSTALLROOT/$PH|$INSTALL_BASE|g" \
        -e "s|${PKG_DIR}|$INSTALL_BASE|g" \
        "${THISDIR}/$f"
      rm -f "${THISDIR}/${f}.unrelocated"
    fi
  done < "${THISDIR}/etc/profile.d/.bits-relocate"
fi

# Update PKG_DIR to new install location
sed -i.unrelocated -e "s|^PKG_DIR=.*|PKG_DIR=\"${INSTALL_BASE}\"|" "$THISDIR/etc/profile.d/.bits-pkginfo"
rm -f "$THISDIR/etc/profile.d/.bits-pkginfo.unrelocated"

# Run post-relocate.sh if it exists (skip for defaults-* packages)
# Extract PKGNAME from PP (format: arch/[family/]name/version)
PKGNAME_FROM_PP=$(echo "$PP" | awk -F'/' '{print $(NF-1)}')
if [[ "$PKGNAME_FROM_PP" != defaults-* ]] && [[ -f "$THISDIR/etc/profile.d/post-relocate.sh" ]]; then
  export PP
  export WORK_DIR="$INSTALL_BASE"
  bash -ex "$THISDIR/etc/profile.d/post-relocate.sh"
fi
