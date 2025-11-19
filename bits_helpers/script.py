import os
from collections import OrderedDict

class GenerateScript:
    def __init__(self, spec: OrderedDict) -> None:
        self.spec = spec

    def write(self, scriptDir, generator, file:str):
        with open(os.path.join(scriptDir, file), "w") as f:
            f.write(generator())

    def generate_rpm_spec(self):
        content = [
            '%define __os_install_post %{nil}\n',
            '%define __spec_install_post %{nil}\n',
            '%define _empty_manifest_terminate_build 0\n',
            '%define _use_internal_dependency_generator 0\n',
            '%define _source_payload w9.gzdio\n',
            '%define _binary_payload w9.gzdio\n',
            '\n',
            f'Name: {self.spec["package"]}_$PKGHASH\n',  # Pass without the initial $
            f'Version: $PKGVERSION\n',
            f'Release: $PKGREVISION\n',
            'Summary: $PKG_NAME built as a part of CMS\n',
            'BuildArch: x86_64\n',
            'License: CMS \n',
        ]

        full_requires = self.spec.get("full_runtime_requires", set())
        if full_requires:
            for dep in sorted(full_requires):
                dep_clean = dep.lower().replace('-', '_')
                dep_upper = dep_clean.upper()
                content.append(f"Requires: {dep_clean}_${{{dep_upper}_VERSION}}_${{{dep_upper}_REVISION}}_${{{dep_upper}_HASH}}\n")

        content.append('\n%description\n')
        content.append('CMS package for $PKG_NAME\n')
        content.append('Built on: $(hostname)\n')
        content.append('Build date: $(date)\n')

        content.append('\n%install\n')
        content.append('cp -a $WORK_DIR/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/* %{buildroot}/\n')
        content.append('find %{buildroot} -type f -exec chmod u+w {} \\;\n')
        content.append('find %{buildroot} -type d -exec chmod u+w {} \\;\n')
        content.append('\n%files\n')
        content.append('/*\n')

        return ''.join(content)
    
    def rpm_command(self):
        return """
mkdir -p "$WORK_DIR/rpmbuild"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
chmod -R u+w "$WORK_DIR/rpmbuild"
cp $WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/$PKGNAME.spec $WORK_DIR/rpmbuild/SPECS/
source "$WORK_DIR/$ARCHITECTURE/rpm/latest/etc/profile.d/init.sh"
rpmbuild -bb --define "_topdir $WORK_DIR/rpmbuild" --define   "buildroot $WORK_DIR/rpmbuild/BUILDROOT/$PKGNAME" "$WORK_DIR/rpmbuild/SPECS/$PKGNAME.spec"
"""
    