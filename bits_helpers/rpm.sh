check_rpm_dependencies() {
    local requires_path="$1"
    local provides_path="$2"

    # Call the Python dependency checker
    python3 "${BITS_SCRIPT_DIR}/bits_helpers/check_dependencies.py" "$requires_path" "$provides_path"
    return $?
}

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

    rpm -qp --requires "$RPM_FILE" | jq -R -n '[inputs | sub("^\\s+";"") | sub("\\s+$";"") | select(length > 0)]' > "$RPM_DB_DIR/requires.json"
    rpm -qp --provides "$RPM_FILE" | jq -R -n '[inputs | sub("^\\s+";"") | sub("\\s+$";"") | select(length > 0)]' > "$RPM_DB_DIR/provides.json"

    PROVIDES_FILES=""
    if [ -f "$RPM_DB_DIR/provides.json" ]; then
        PROVIDES_FILES="$RPM_DB_DIR/provides.json"
    fi

    for req in $REQUIRES; do
        if [[ $req == defaults-* ]]; then
            continue
        fi
        req_upper=$(echo "$req" | tr '[:lower:]' '[:upper:]' | tr '-' '_')
        root_var="${req_upper}_ROOT"
        pkg_root="${!root_var}"
        if [ -n "$pkg_root" ] && [ -f "$pkg_root/etc/rpm/provides.json" ]; then
            PROVIDES_FILES="$PROVIDES_FILES $pkg_root/etc/rpm/provides.json"
        fi
    done

    if [ -n "$PROVIDES_FILES" ]; then
        jq -s 'add' $PROVIDES_FILES > "$RPM_DB_DIR/all_provides.json"
    else
        echo "[]" > "$RPM_DB_DIR/all_provides.json"
    fi

else
    echo "Error: Expected RPM not found at $RPM_FILE"
    exit 1
fi
echo "Checking dependencies for $PKGNAME"
echo "$PROVIDES_FILES"
check_rpm_dependencies "$WORK_DIR" "$RPM_DB_DIR/requires.json" "$PROVIDES_FILES" 

