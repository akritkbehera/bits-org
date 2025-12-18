if [ ! -f "$WORK_DIR/rpmbuild/RPMS/$(uname -m)/system-provides-1-1.$(uname -m).rpm" ]; then
  mkdir -p "$WORK_DIR/rpmbuild"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
  cp $WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/system-provides.spec "$WORK_DIR/rpmbuild/SPECS/system-provides.spec"
  rpmbuild -bb \
    --define "_topdir $WORK_DIR/rpmbuild" \
    --define "_buildarch $(uname -m)" \
    "$WORK_DIR/rpmbuild/SPECS/system-provides.spec"
fi

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
  
  requires+=(${PKGNAME}_${PKGVERSION}_${PKGREVISION}_${PKGHASH})
  requires+=(system-provides)
  rpm -qp --queryformat '%{NAME}\n[%{PROVIDES}\n]' /home/akbehera/Desktop/repositories/rpm_1/rpmbuild/RPMS/x86_64/system-provides-1-1.x86_64.rpm
  for f in "${requires[@]}"; do
    rpm_file="${f}-1-1.$(uname -m).rpm"
    rpm -qp --queryformat "%{NAME}\n[%{PROVIDES}\n]" \
        "$WORK_DIR/rpmbuild/RPMS/$(uname -m)/$rpm_file" | \
        jq -R -s '
            split("\n") | 
            map(select(length > 0)) | 
            { (.[0]): .[1:] }
        '
  done | jq -s 'add' > "$WORK_DIR/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/provides.json"

  rpm -qp --queryformat "%{NAME}\n[%{REQUIRES}\n]" "$WORK_DIR/rpmbuild/RPMS/$(uname -m)/${PKGNAME}_${PKGVERSION}_${PKGREVISION}_${PKGHASH}-1-1.$(uname -m).rpm" | \
  jq -R -s '
    split("\n")
    | map(select(length > 0))
    | { (.[0]): .[1:] }
  ' > "$WORK_DIR/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/requires.json"
fi