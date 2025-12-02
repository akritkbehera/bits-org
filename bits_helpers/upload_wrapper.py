import argparse
import json
import sys
import os
from bits_helpers.upload import createDistLinks, uploadPackage
from bits_helpers.sync import remote_from_url


def main():
    parser = argparse.ArgumentParser(description="Upload package wrapper for Makeflow")
    parser.add_argument("--package", required=True, help="Package name to upload")
    parser.add_argument("--specs-file", required=True, help="Path to specs.json file")
    parser.add_argument("--work-dir", required=True, help="Working directory")
    parser.add_argument("--architecture", required=True, help="Architecture")
    parser.add_argument("--remote-store", required=True, help="Remote store URL (read)")
    parser.add_argument("--write-store", required=True, help="Write store URL (upload)")

    args = parser.parse_args()

    # Load specs
    try:
        with open(args.specs_file, "r") as f:
            specs = json.load(f)
    except Exception as e:
        print(f"Error loading specs from {args.specs_file}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.package not in specs:
        print(f"Package {args.package} not found in specs", file=sys.stderr)
        sys.exit(1)

    spec = specs[args.package]

    # Initialize syncHelper
    # We need to construct a dummy args object for createDistLinks because it expects 'args' with workDir and architecture
    class DummyArgs:
        def __init__(self, workDir, architecture):
            self.workDir = workDir
            self.architecture = architecture

    dummy_args = DummyArgs(args.work_dir, args.architecture)

    # Initialize syncHelper
    syncHelper = remote_from_url(
        args.remote_store, args.write_store, args.architecture, args.work_dir
    )

    # We need to manually set writeStore if it wasn't set by remote_from_url (e.g. for S3/Boto3 it might be parsed differently)
    # However, remote_from_url handles the logic based on the URL scheme.
    # Let's trust remote_from_url to set it up correctly, but we might need to ensure writeStore is set if it's passed explicitly.
    # Looking at sync.py, remote_from_url takes write_url as second argument.

    print(f"Uploading {args.package}...")

    try:
        createDistLinks(spec, specs, dummy_args, syncHelper, "dist", "full_requires")
        createDistLinks(spec, specs, dummy_args, syncHelper, "dist-direct", "requires")
        createDistLinks(
            spec, specs, dummy_args, syncHelper, "dist-runtime", "full_runtime_requires"
        )
        uploadPackage(spec, syncHelper)
        print(f"Successfully uploaded {args.package}")
    except Exception as e:
        print(f"Error uploading {args.package}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
