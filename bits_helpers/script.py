import os
from collections import OrderedDict

class GenerateScript:
    def __init__(self, spec: OrderedDict) -> None:
        self.spec = spec

    def write(self, scriptDir, generator, file:str):
        with open(os.path.join(scriptDir, file), "w") as f:
            f.write(generator())

    def generate_rpm_spec(self):
        """
        Generates the content of a self-contained shell script that:
        1. Writes the spec.in template
        2. Expands it via envsubst to .spec
        3. Builds the RPM
        """
        # Build the RPM spec template lines
        spec_lines = [
            '%define __os_install_post %{nil}',
            '%define __spec_install_post %{nil}',
            '%define _empty_manifest_terminate_build 0',
            '%define _use_internal_dependency_generator 0',
            '%define _source_payload w9.gzdio',
            '%define _binary_payload w9.gzdio',
            '',
            f'Name: {self.spec["package"]}_{self.spec["version"]}_{self.spec["revision"]}_$PKGHASH',
            'Version: $PKGVERSION',
            'Release: $PKGREVISION',
            'Summary: $PKG_NAME built as a part of CMS',
            'BuildArch: %s' % os.uname().machine,
            'License: CMS',
        ]

        # Add runtime dependencies if present
        build_requires = self.spec.get("full_build_requires", set())
        for dep in sorted(build_requires):
            if dep.startswith("defaults-"):
                continue
            dep_clean = dep.lower().replace('-', '_')
            dep_upper = dep_clean.upper()
            spec_lines.append(
                f"BuildRequires: {dep_clean}_${{{dep_upper}_VERSION}}_${{{dep_upper}_REVISION}}_${{{dep_upper}_HASH}}"
            )

        # Requires
        full_requires = self.spec.get("full_runtime_requires", set())
        for dep in sorted(full_requires):
            if dep.startswith("defaults-"):
                continue
            dep_clean = dep.lower().replace('-', '_')
            dep_upper = dep_clean.upper()
            spec_lines.append(
                f"Requires: {dep_clean}_${{{dep_upper}_VERSION}}_${{{dep_upper}_REVISION}}_${{{dep_upper}_HASH}}"
            )

        spec_lines.extend([
            '',
            '%description',
            'CMS package for %s' % self.spec["package"],
            'Built on: %s' % os.uname().nodename,
            '',
            '%install',
            'cp -a $WORK_DIR/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/* %{buildroot}/',
            'find %{buildroot} -type f -exec chmod u+w {} \\;',
            'find %{buildroot} -type d -exec chmod u+w {} \\;',
            '',
            '%files',
            '/*',
        ])

        spec_text = "\n".join(spec_lines)

        # Return the shell script content as a string
        script = f"""#!/bin/bash

# 1 Create RPM build directories
mkdir -p "$WORK_DIR/rpmbuild"/{{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}}
chmod -R u+w "$WORK_DIR/rpmbuild"

# 2 Write literal spec.in template (variables preserved)
SPEC_IN="$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/$PKGNAME.spec.in"
cat <<'EOF' > "$SPEC_IN"
{spec_text}
EOF

# 3 Expand variables into final .spec
SPEC_OUT="$WORK_DIR/rpmbuild/SPECS/$PKGNAME.spec"
envsubst < "$SPEC_IN" > "$SPEC_OUT"

# 4 Load RPM environment
source "$WORK_DIR/$ARCHITECTURE/rpm/latest/etc/profile.d/init.sh"

# 5 Build the RPM
rpmbuild -bb \\
    --define "_topdir $WORK_DIR/rpmbuild" \\
    --define "buildroot $WORK_DIR/rpmbuild/BUILDROOT/$PKGNAME" \\
    "$SPEC_OUT"
"""

        return script
    