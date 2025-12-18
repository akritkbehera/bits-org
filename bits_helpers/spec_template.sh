#!/bin/bash
# We don't build RPMs if we have requires.json and provides.json. We can just proceed with checking dependencies.
if [ -f "$INSTALLROOT/etc/requires.json" ] && [ -f "$INSTALLROOT/etc/provides.json" ]; then
  exit 0
fi

# Build system-provides RPM and extract provides.json and store in $WORK_DIR/provides.json from where it will be copied by into each package provides.json
if [ ! -f "$WORK_DIR/rpmbuild/RPMS/$(uname -m)/system-provides-1-1.$(uname -m).rpm" ]; then
  mkdir -p "$WORK_DIR/rpmbuild"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
  cp $WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/system-provides.spec "$WORK_DIR/rpmbuild/SPECS/system-provides.spec"
  rpmbuild -bb \
    --define "_topdir $WORK_DIR/rpmbuild" \
    --define "_buildarch $(uname -m)" \
    "$WORK_DIR/rpmbuild/SPECS/system-provides.spec"
  
  rpm -qp --queryformat "%{NAME}\n[%{PROVIDES}\n]" "$WORK_DIR/rpmbuild/RPMS/$(uname -m)/system-provides-1-1.$(uname -m).rpm" | \
  jq -R -s '
    split("\n")
    | map(select(length > 0))
    | { (.[0]): .[1:] }
  ' > "$WORK_DIR/provides.json"
fi

if [ "$PKGNAME" != defaults-* ] && [ -f "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/${PKGNAME}.spec" ]; then
  mkdir -p "$WORK_DIR/rpmbuild"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
  mkdir -p "$WORK_DIR/rpmbuild/BUILDROOT/${PKGNAME}"
  chmod -R u+w "$WORK_DIR/rpmbuild" 
  source "$WORK_DIR/$ARCHITECTURE/rpm/latest/etc/profile.d/init.sh" || true
  cp "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/${PKGNAME}.spec" "$WORK_DIR/rpmbuild/SPECS/"
  requires=()
  for f in $REQUIRES; do
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
    --define "installroot $INSTALLROOT" \
    --define "requires $requires_str" \
    --define "_topdir $WORK_DIR/rpmbuild" \
    --define "buildroot $WORK_DIR/rpmbuild/BUILDROOT/${PKGNAME}" \
    "$WORK_DIR/rpmbuild/SPECS/${PKGNAME}.spec"

  rpm -qp --queryformat "%{NAME}\n[%{REQUIRES}\n]" "$WORK_DIR/rpmbuild/RPMS/$(uname -m)/${PKGNAME}_${PKGVERSION}_${PKGREVISION}_${PKGHASH}-1-1.$(uname -m).rpm" | \
  jq -R -s '
    split("\n")
    | map(select(length > 0))
    | { (.[0]): .[1:] }
  ' > "$INSTALLROOT/etc/requires.json"

  rpm -qp --queryformat "%{NAME}\n[%{PROVIDES}\n]" "$WORK_DIR/rpmbuild/RPMS/$(uname -m)/${PKGNAME}_${PKGVERSION}_${PKGREVISION}_${PKGHASH}-1-1.$(uname -m).rpm" | \
  jq -R -s '
    split("\n")
    | map(select(length > 0))
    | { (.[0]): .[1:] }
  ' > "$INSTALLROOT/etc/provides.json"

  # Collect all provides.json for all the package mentioned in $REQUIRES and also system-provides.json and create a single provides.json file from where we can see if each
  # REQUIRES is satisfied or not.
  provides_files=("$INSTALLROOT/etc/provides.json")
  provides_files+=("$WORK_DIR/provides.json")

  for f in $REQUIRES; do
    if [[ "$f" == "defaults-"* ]]; then
      continue
    fi
    F=${f^^}
    F=${F//-/_}
    hash="${F}_HASH"
    ver="${F}_VERSION"
    rev="${F}_REVISION"
    
    provides_file="${WORK_DIR}/$ARCHITECTURE/$f/${!ver}-${!rev}/etc/provides.json"
    
    if [ -f "$provides_file" ]; then
      provides_files+=("$provides_file")
    fi
  done

  # Merge all provides.json files into a single file and store it in $INSTALLROOT/etc/provides.json
  jq -s 'reduce .[] as $item ({}; . * $item)' "${provides_files[@]}" > "$INSTALLROOT/provides.json"
  rm $INSTALLROOT/etc/provides.json
  mv $INSTALLROOT/provides.json $INSTALLROOT/etc/provides.json
fi