import os

with open("build_template.sh", "r") as f:
    lines = f.readlines()

# Robustly find the cut point
idx = -1
for i, line in enumerate(lines):
    if "export BITS_CONFIG_DIR" in line:
        idx = i
        break

if idx == -1:
    print("Could not find anchor line. Aborting.")
    exit(1)

tail = lines[idx:]

header = """#!/bin/bash
BITS_START_TIMESTAMP=$(date +%%s)
# Automatically generated build script
unset DYLD_LIBRARY_PATH
echo "bits: start building $PKGNAME-$PKGVERSION-$PKGREVISION at $BITS_START_TIMESTAMP"

  get_file() {
      [[ -z "$BITS_PATH" ]] && echo "$BITS_CONFIG_DIR/$1" && return
      eval ls -1 "\\"$(dirname "$BITS_CONFIG_DIR")\\"/{${BITS_PATH//,/.bits,}.bits}/\\"$1\\"" 2>/dev/null | head -n 1
  }

cleanup() {
  local exit_code=$?
  BITS_END_TIMESTAMP=$(date +%%s)
  BITS_DELTA_TIME=$(($BITS_END_TIMESTAMP - $BITS_START_TIMESTAMP))
  echo "bits: done building $PKGNAME-$PKGVERSION-$PKGREVISION at $BITS_START_TIMESTAMP (${BITS_DELTA_TIME} s)"
  exit $exit_code
}

trap cleanup EXIT

# Cleanup variables which should not be exposed to user code
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY

set -e
set +h

cversion=$(gcc --version | head -n 1)
cpath=$(which gcc)

function hash() { true; }

export WORK_DIR="${WORK_DIR_OVERRIDE:-%(workDir)s}"
"""

with open("build_template.sh", "w") as f:
    f.write(header)
    f.writelines(tail)

print("Restored successfully.")
