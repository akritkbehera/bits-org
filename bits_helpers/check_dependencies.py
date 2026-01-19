#!/usr/bin/env python3
"""
RPM Dependency Checker using rpm.labelCompare
Validates that all requirements in requires.json are satisfied by provides.json
"""

import json
import re
import rpm
import sys
import os

# Ensure we import from the local bits_helpers package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bits_helpers.log import debug, info, banner, warning, dieOnError

def parse_rpm_dependency(dep_string):
    """
    Parse an RPM dependency string into components.

    Examples:
        "package-name >= 1.2.3-1" -> ("package-name", ">=", "1.2.3-1")
        "package-name" -> ("package-name", None, None)
        "package-name = 1:2.3.4-5" -> ("package-name", "=", "1:2.3.4-5")

    Returns:
        tuple: (name, operator, version) where operator and version may be None
    """
    # Pattern to match: name [operator version]
    # Handles epoch:version-release format (e.g., 1:2.3.4-5)
    pattern = r'^(.+?)\s*([<>=]+)?\s*(\S+)?$'
    match = re.match(pattern, dep_string.strip())

    if not match:
        return (dep_string.strip(), None, None)

    name = match.group(1).strip()
    operator = match.group(2).strip() if match.group(2) else None
    version = match.group(3).strip() if match.group(3) else None

    return (name, operator, version)


def split_evr(version_string):
    """
    Split version string into (epoch, version, release).

    Examples:
        "1:2.3.4-5" -> ("1", "2.3.4", "5")
        "2.3.4-5" -> ("", "2.3.4", "5")
        "2.3.4" -> ("", "2.3.4", "")

    Returns:
        tuple: (epoch, version, release)
    """
    if not version_string:
        return ("", "", "")

    epoch = ""
    version = version_string
    release = ""

    # Check for epoch (e.g., "1:2.3.4-5")
    if ':' in version_string:
        epoch, version_string = version_string.split(':', 1)

    # Check for release (e.g., "2.3.4-5")
    if '-' in version_string:
        version, release = version_string.rsplit('-', 1)
    else:
        version = version_string

    return (epoch, version, release)


def compare_versions(required_op, required_ver, provided_ver):
    """
    Compare versions using rpm.labelCompare.

    Args:
        required_op: Operator from requirement (e.g., ">=", "=", "<")
        required_ver: Required version string
        provided_ver: Provided version string

    Returns:
        bool: True if the requirement is satisfied
    """
    if not required_op or not required_ver:
        # No version constraint, any provide satisfies
        return True

    req_epoch, req_version, req_release = split_evr(required_ver)
    prov_epoch, prov_version, prov_release = split_evr(provided_ver)

    # rpm.labelCompare takes tuples of (epoch, version, release)
    result = rpm.labelCompare(
        (req_epoch, req_version, req_release),
        (prov_epoch, prov_version, prov_release)
    )

    # result: -1 if required < provided, 0 if equal, 1 if required > provided
    if required_op in ('=', '=='):
        return result == 0
    elif required_op in ('>=', '=>'):
        return result <= 0  # required <= provided
    elif required_op == '>':
        return result < 0   # required < provided
    elif required_op in ('<=', '=<'):
        return result >= 0  # required >= provided
    elif required_op == '<':
        return result > 0   # required > provided
    else:
        # Unknown operator, be conservative
        return False


def check_dependencies(requires_json_path, provides_json_path):
    """
    Check if all requirements are satisfied by the provides.

    Args:
        requires_json_path: Path to requires.json
        provides_json_path: Path to provides.json

    Returns:
        dict: {
            "satisfied": bool,
            "missing": list of unsatisfied requirements,
            "details": list of dicts with requirement details
        }
    """
    # Load JSON files
    with open(requires_json_path, 'r') as f:
        requires = json.load(f)

    with open(provides_json_path, 'r') as f:
        provides = json.load(f)

    # Parse all provides into a dict: {name: [versions]}
    provides_map = {}
    for provide in provides:
        name, _, version = parse_rpm_dependency(provide)
        if name not in provides_map:
            provides_map[name] = []
        if version:
            provides_map[name].append(version)
        else:
            # If no version specified, it provides any version
            provides_map[name].append(None)

    # Check each requirement
    missing = []
    details = []

    for require in requires:
        req_name, req_op, req_ver = parse_rpm_dependency(require)

        # Skip special RPM automatic dependencies
        if req_name.startswith('rpmlib(') or req_name.startswith('/'):
            continue

        satisfied = False
        matched_version = None

        if req_name in provides_map:
            # Check if any provided version satisfies the requirement
            for prov_ver in provides_map[req_name]:
                if prov_ver is None:
                    # Provider doesn't specify version, satisfies any requirement
                    satisfied = True
                    matched_version = "any"
                    break
                elif compare_versions(req_op, req_ver, prov_ver):
                    satisfied = True
                    matched_version = prov_ver
                    break

        detail = {
            "requirement": require,
            "name": req_name,
            "operator": req_op,
            "version": req_ver,
            "satisfied": satisfied,
            "matched_version": matched_version
        }
        details.append(detail)

        if not satisfied:
            missing.append(require)

    return {
        "satisfied": len(missing) == 0,
        "missing": missing,
        "details": details
    }


# def main():
#     """Example usage"""

#     requires_path = "/home/akbehera/Desktop/repositories/rpm_sw/slc9_x86-64/go/latest/etc/rpm/requires.json"
#     provides_path = "/home/akbehera/Desktop/repositories/rpm_sw/slc9_x86-64/go/latest/etc/rpm/provides.json"

#     result = check_dependencies(requires_path, provides_path)

#     print(f"All dependencies satisfied: {result['satisfied']}")
#     print(f"\nTotal requirements: {len(result['details'])}")
#     print(f"Missing: {len(result['missing'])}")

#     if result['missing']:
#         print("\nUnsatisfied requirements:")
#         for req in result['missing']:
#             print(f"  - {req}")

#     print("\nDetailed analysis:")
#     for detail in result['details']:
#         status = "✓" if detail['satisfied'] else "✗"
#         matched = f" (matched: {detail['matched_version']})" if detail['matched_version'] else ""
#         print(f"  {status} {detail['requirement']}{matched}")

#     sys.exit(0 if result['satisfied'] else 1)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: check_dependencies.py <requires.json> <provides.json>")
        sys.exit(1)

    requires_path = sys.argv[1]
    provides_path = sys.argv[2]

    result = check_dependencies(requires_path, provides_path)

    banner(f"All dependencies satisfied: {result['satisfied']}")
    debug(f"\nTotal requirements: {len(result['details'])}")
    warning(f"Missing: {len(result['missing'])}")

    if result['missing']:
        for req in result['missing']:
            warning(f"  - {req}")
        dieOnError("Missing dependencies", "\nUnsatisfied requirements:")

    debug("\nDetailed analysis:")
    for detail in result['details']:
        status = "✓" if detail['satisfied'] else "✗"
        matched = f" (matched: {detail['matched_version']})" if detail['matched_version'] else ""
        debug(f"  {status} {detail['requirement']}{matched}")

    sys.exit(0 if result['satisfied'] else 1)
