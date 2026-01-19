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
import yaml

# Add parent directory to path so bits_helpers can be imported when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bits_helpers.log import debug, info, banner, warning, dieOnError
from bits_helpers.utilities import yamlLoad

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
    # We explicitly look for the operator to avoid splitting simple names
    pattern = r'^(.+?)\s*([<>=]+)\s*(\S+)$'
    match = re.match(pattern, dep_string.strip())

    if match:
        name = match.group(1).strip()
        operator = match.group(2).strip()
        version = match.group(3).strip()
        return (name, operator, version)
    else:
        # No operator found, assume it is just the name (capability)
        return (dep_string.strip(), None, None)


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
    if ':' in version_string:
        epoch, version_string = version_string.split(':', 1)
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
        return True

    req_epoch, req_version, req_release = split_evr(required_ver)
    prov_epoch, prov_version, prov_release = split_evr(provided_ver)

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
        return False


def check_dependencies(global_provides_path, pkg_root, dependencies_root=None):
    requires_path = os.path.join(pkg_root, "requires.json")
    with open(requires_path, 'r') as f:
        requires = json.load(f)
    all_provides = []
    local_provides_path = os.path.join(pkg_root, "provides.json")
    if os.path.exists(local_provides_path):
        with open(local_provides_path, 'r') as f:
            all_provides.extend(json.load(f))
    if not dependencies_root:
        paths = []
    elif isinstance(dependencies_root, str):
        paths = dependencies_root.split()
    else:
        paths = dependencies_root

    for path in paths:
        if path and os.path.exists(path):
            with open(path, 'r') as f:
                all_provides.extend(json.load(f))
    global_provs = get_global_provides(get_global_provides_path)
    all_provides.extend(global_provs)
    provides_map = {}
    for provide in all_provides:
        name, _, version = parse_rpm_dependency(provide)
        name_lower = name.lower()
        if name_lower not in provides_map:
            provides_map[name_lower] = []
        if version:
            provides_map[name_lower].append(version)
        else:
            provides_map[name_lower].append(None)

    missing = []
    details = []

    for require in requires:
        req_name, req_op, req_ver = parse_rpm_dependency(require)

        if req_name.startswith('rpmlib(') or req_name.startswith('/'):
            continue

        satisfied = False
        matched_version = None
        
        req_name_lower = req_name.lower()

        if req_name_lower in provides_map:
            for prov_ver in provides_map[req_name_lower]:
                if prov_ver is None:
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

def get_global_provides(path):
    global_provides_list = set()
    file_path = os.path.join(path, "bootstrap_provides.sh")
    if os.path.exists(file_path):
        ts = rpm.TransactionSet()
        with open(file_path, 'r') as reader:
            d = reader.read()
            header_content = d.split("---", 1)[0]
            if header_content:
                header = yamlLoad(header_content)
                seeds = header.get("platformSeeds", [])
                for seed in seeds:
                    if seed.startswith("/"):
                        mi = ts.dbMatch(rpm.RPMTAG_PROVIDENAME, seed)
                        for h in mi:
                            if h['provides']:
                                for p in h['provides']:
                                    global_provides_list.add(p)
                    else:
                        mi = ts.dbMatch('name', seed)
                        for h in mi:
                            if h['provides']:
                                for p in h['provides']:
                                    global_provides_list.add(p)
    return list(global_provides_list)
