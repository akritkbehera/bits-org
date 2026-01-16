mkdir -p "$WORK_DIR/rpmbuild"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
chmod -R u+w "$WORK_DIR/rpmbuild"
cp "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/${PKGNAME}.spec" "$WORK_DIR/rpmbuild/SPECS/"
FULL_REQUIRES=""
for req in $REQUIRES; do
    if [[ $req == defaults-* ]]; then
        continue
    fi
    req_upper=$(echo "$req" | tr '[:lower:]' '[:upper:]' | tr '-' '_')
    hash_var="${req_upper}_HASH"
    req_hash="${!hash_var}"
    # Convention: NAME_HASH-1-1.ARCH
    # Note: Using dot separator for architecture to match rpm_name definition below.
    dep_name="${req_upper}_${req_hash}-1-1.${ARCHITECTURE}"
    if [ -z "$FULL_REQUIRES" ]; then
        FULL_REQUIRES="Requires: ${dep_name}"
    else
        FULL_REQUIRES="${FULL_REQUIRES}, ${dep_name}"
    fi
done

if [ -z "$FULL_REQUIRES" ]; then
    FULL_REQUIRES="%{nil}"
fi

rpmbuild -bb \
    --define "rpm_name ${PKGNAME}_${PKGHASH}-1-1.${ARCHITECTURE}" \
    --define "full_requires ${FULL_REQUIRES}" \
    --define "version ${PKGVERSION}" \
    --define "revision ${PKGREVISION}" \
    --define "arch ${ARCHITECTURE}" \
    --define "pkgname ${PKGNAME}" \
    --define "work_dir ${WORK_DIR}" \
    --define "summary ${PKGNAME} ${PKGVERSION}-${PKGREVISION}" \
    --define "_topdir $WORK_DIR/rpmbuild" \
    --define "buildroot $WORK_DIR/rpmbuild/BUILDROOT/${PKGNAME}" \
    "$WORK_DIR/rpmbuild/SPECS/${PKGNAME}.spec" || exit 1

RPM_FILE="$WORK_DIR/rpmbuild/RPMS/${PKGNAME}_${PKGHASH}-1-1.${ARCHITECTURE}.rpm"

if [ -f "$RPM_FILE" ]; then
    RPM_DB_DIR="$WORK_DIR/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/etc/rpm"
    mkdir -p "$RPM_DB_DIR"

    rpm -qp --provides "$RPM_FILE" | python3 -c 'import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' > "$RPM_DB_DIR/provides.json"
    rpm -qp --requires "$RPM_FILE" | python3 -c 'import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' > "$RPM_DB_DIR/requires.json"

    # Manage global_provides.json
    GLOBAL_PROVIDES="$WORK_DIR/rpmbuild/global_provides.json"
    CURRENT_PROVIDES=$(rpm -qp --provides "$RPM_FILE" | python3 -c 'import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')

    if [ -f "$GLOBAL_PROVIDES" ]; then
        # Copy global_provides, append current package's provides, save back
        python3 -c "
import json
with open('$GLOBAL_PROVIDES') as f:
    global_provides = json.load(f)
current_provides = json.loads('$CURRENT_PROVIDES')
merged = list(set(global_provides + current_provides))
with open('$RPM_DB_DIR/provides.json', 'w') as f:
    json.dump(merged, f)
"
    else
        # No global_provides yet, create provides.json with current package's provides
        echo "$CURRENT_PROVIDES" > "$RPM_DB_DIR/provides.json"
    fi

    # Copy provides.json back to global_provides.json
    cp "$RPM_DB_DIR/provides.json" "$GLOBAL_PROVIDES"

    echo "Stored RPM json metadata in $RPM_DB_DIR"

    # Cleanup global_provides.json if this is the requested package
    if [[ " $REQUESTED_PKG " == *" $PKGNAME "* ]]; then
        rm -f "$GLOBAL_PROVIDES"
        echo "Cleaned up global_provides.json (requested package: $PKGNAME)"
    fi
else
    echo "Error: Expected RPM not found at $RPM_FILE"
    exit 1
fi 