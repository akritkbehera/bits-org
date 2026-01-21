#!/bin/bash -e
THISDIR="$(cd -P "$(dirname "$0")" && pwd)"
source ${THISDIR}/etc/profile.d/.bits-pkginfo
INSTALL_BASE=$(echo $THISDIR | sed "s|/$PP$||")
if [[ -s ${THISDIR}/etc/profile.d/.bits-relocate ]] ; then
  for f in $(cat ${THISDIR}/etc/profile.d/.bits-relocate) ; do
    sed -i.unrelocated -e "s|${PKG_DIR}/INSTALLROOT/$PH|$INSTALL_BASE|g;s|${PKG_DIR}|$INSTALL_BASE|g" "${THISDIR}/$f"
    rm -f "${THISDIR}/${f}.unrelocated"
  done
fi
sed -i.unrelocated -e "s|^PKG_DIR=.*|PKG_DIR="${INSTALL_BASE}"|" "$THISDIR/etc/profile.d/.bits-pkginfo"
rm -f "$THISDIR/etc/profile.d/.bits-pkginfo.unrelocated"

# Run the post-relocate script if it was created.
if [ -f "$THISDIR/etc/profile.d/post-relocate.sh" ]; then
  bash -ex "$THISDIR/etc/profile.d/post-relocate.sh"
fi

