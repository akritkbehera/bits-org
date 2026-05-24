#!/usr/bin/env python3
import os
import sys
from unittest.mock import MagicMock

# Mock yaml in case it is not installed in the current python3 environment
sys.modules['yaml'] = MagicMock()

# Add the script directory to the path to import bits_helpers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bits_helpers.utilities import resolve_spec_data, SpecError

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 resolve_script.py <template_file>", file=sys.stderr)
        sys.exit(1)
        
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.", file=sys.stderr)
        sys.exit(1)
        
    try:
        with open(filepath, "r") as f:
            data = f.read()
    except OSError as e:
        print(f"Error reading file '{filepath}': {e}", file=sys.stderr)
        sys.exit(1)
        
    import json
    
    # Build spec context and resolution parameters
    if "BITS_SPEC_JSON" in os.environ:
        try:
            spec = json.loads(os.environ["BITS_SPEC_JSON"])
        except Exception as e:
            print(f"Error loading BITS_SPEC_JSON: {e}", file=sys.stderr)
            sys.exit(1)
            
        try:
            defaults = json.loads(os.environ.get("BITS_SPEC_DEFAULTS", "[]"))
        except Exception:
            defaults = ["release"]
            
        branch_basename = os.environ.get("BITS_SPEC_BRANCH_BASENAME", "")
        branch_stream = os.environ.get("BITS_SPEC_BRANCH_STREAM", "")
        
        # Merge os.environ into spec variables so environment variables are also resolvable
        spec_vars = spec.get("variables", {})
        merged_vars = {}
        if isinstance(spec_vars, dict):
            merged_vars.update(spec_vars)
        merged_vars.update(os.environ)
        spec["variables"] = merged_vars
    else:
        # Build spec context. Environment variables are loaded into spec["variables"]
        # so any environment variable can be resolved via %(VAR)s in the template.
        spec = {
            "package": "generic",
            "version": os.environ.get("VERSION", "version_unknown"),
            "pkgdir": os.path.dirname(os.path.abspath(filepath)) or ".",
            "variables": dict(os.environ),
        }
        defaults = ["release"]
        branch_basename = ""
        branch_stream = ""
    
    try:
        resolved = resolve_spec_data(spec, data, defaults, branch_basename, branch_stream)
        print(resolved, end="")
    except SpecError as e:
        print(f"SpecError during resolution: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
