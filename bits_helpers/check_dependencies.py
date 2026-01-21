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
from shlex import quote

from bits_helpers.log import debug, info, banner, warning, dieOnError
from bits_helpers.utilities import yamlLoad, resolveFilename

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

    epoch = None
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


def check_dependencies(config_dir, work_dir, pkg_root, dependencies_root=None):
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
    get_system_provides(config_dir, work_dir)
    global_provs_path = os.path.join(work_dir, "system_provides.json")
    if os.path.exists(global_provs_path):
        with open(global_provs_path, 'r') as f:
            all_provides.extend(json.load(f))
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
                    # Unversioned provide only satisfies unversioned requirement
                    if not req_ver:
                        satisfied = True
                        matched_version = "none"
                        break
                    # Else continue, unversioned provide cannot satisfy versioned requirement
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

def get_system_provides(configDir, work_dir):
    global_provides_list = set()
    file_tuple = resolveFilename({}, "bootstrap_provides", configDir, {})
    file_path = file_tuple[0]
    ts = rpm.TransactionSet()
    header = {}
    cmd = ""
    with open(file_path, 'r') as reader:
        d = reader.read()
        header_content = d.split("---", 1)[0]
        if header_content:
            header = yamlLoad(header_content)
            env_vars = []
            for key, value in header.items():
                if key == "system_requirement_check":
                    continue
                env_key = re.sub(r'(?<!^)(?=[A-Z])', '_', key).upper()
                val_str = ""
                if isinstance(value, list):
                    val_str = " ".join(str(v) for v in value)
                elif isinstance(value, (str, int, float, bool)):
                    val_str = str(value)
                else:
                    continue
                env_vars.append("{}={}".format(env_key, quote(val_str)))
            cmd = "{env}\n{check}".format(
                env="\n".join(env_vars),
                check=header.get("system_requirement_check", "false"),
            )
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
            provides = header.get("provides", [])
            for p in provides:
                global_provides_list.add(p)
                                
    if work_dir and os.path.exists(work_dir):
        try:
            with open(os.path.join(work_dir, "system_provides.json"), 'w') as f:
                json.dump(list(global_provides_list), f, indent=4)
            with open(os.path.join(work_dir, "system_requirement_check.sh"), 'w') as f:
                f.write(cmd)
        except OSError as e:
            warning("Failed to dump system files: {}".format(e))

    return


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: check_dependencies.py <config_dir> <work_dir> <pkg_root> <dependency_provides>")
        sys.exit(1)

    config_dir = sys.argv[1]
    work_dir = sys.argv[2]
    pkg_root = sys.argv[3]
    dependency_provides = sys.argv[4]

    result = check_dependencies(config_dir, work_dir, pkg_root, dependency_provides)

    debug(f'Result: {result}')
    banner(f'All dependencies satisfied: {result["satisfied"]}')
    debug(f'Total requirements: {len(result["details"])}')
    warning(f'Missing: {len(result["missing"])}')

    if result['missing']:
        for req in result['missing']:
            warning(f'  - {req}')

    debug('Detailed analysis:')
    for detail in result['details']:
        status = '✓' if detail['satisfied'] else '✗'
        matched = f' (matched: {detail["matched_version"]})' if detail['matched_version'] else ''
        debug(f'  {status} {detail["requirement"]}{matched}')

    sys.exit(0 if result['satisfied'] else 1)