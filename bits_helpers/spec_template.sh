if [ "$PKGNAME" != defaults-* ] && [ -f "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/${PKGNAME}.spec" ]; then
  mkdir -p "$WORK_DIR/rpmbuild"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
  mkdir -p "$WORK_DIR/rpmbuild/BUILDROOT/${PKGNAME}"
  chmod -R u+w "$WORK_DIR/rpmbuild" 
  source "$WORK_DIR/$ARCHITECTURE/rpm/latest/etc/profile.d/init.sh" || true
  cp "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/${PKGNAME}.spec" "$WORK_DIR/rpmbuild/SPECS/"
  requires=()
  for f in $FULL_REQUIRES; do
    if [[ "$f" == "defaults-"* ]]; then
      continue
    fi
    F=${f^^}
    F=${F//-/_}
    hash="${F}_HASH"
    ver="${F}_VERSION"
    rev="${F}_REVISION"
    requires+=("${f}_${!ver}_${!rev}_${!hash}")
  done

  if [ ${#requires[@]} -eq 0 ]; then
    requires_str="%{nil}"
  else
    printf -v requires_str '%s ' "${requires[@]}"
    requires_str="${requires_str% }"
  fi

  rpmbuild -bb \
    --define "name ${PKGNAME}_${PKGVERSION}_${PKGREVISION}_${PKGHASH}" \
    --define "pkgname ${PKGNAME}" \
    --define "arch $(uname -m)" \
    --define "path $ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION" \
    --define "workdir $WORK_DIR" \
    --define "requires $requires_str" \
    --define "_topdir $WORK_DIR/rpmbuild" \
    --define "buildroot $WORK_DIR/rpmbuild/BUILDROOT/${PKGNAME}" \
    "$WORK_DIR/rpmbuild/SPECS/${PKGNAME}.spec"
fi