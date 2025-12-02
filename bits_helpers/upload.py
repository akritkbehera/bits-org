import argparse
import pickle
from bits_helpers.build import createDistLinks, uploadPackage


def makeflow_upload(spec, specs, syncHelper):
    createDistLinks(spec, specs, syncHelper, "dist", "full_requires")
    createDistLinks(spec, specs, syncHelper, "dist-direct", "requires")
    createDistLinks(spec, specs, syncHelper, "dist-runtime", "full_runtime_requires")
    uploadPackage(spec, syncHelper)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--specs-file", required=True)
    parser.add_argument("--sync-helper-file", required=True)
    args_parsed = parser.parse_args()

    with open(args_parsed.specs_file, "rb") as f:
        specs = pickle.load(f)
    with open(args_parsed.sync_helper_file, "rb") as f:
        syncHelper = pickle.load(f)

    spec = specs[args_parsed.package_name]
    makeflow_upload(spec, specs, syncHelper)
