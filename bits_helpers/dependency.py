import os
import subprocess
import shutil
import glob
import json
from typing import Dict, List, Optional, Set
from bits_helpers.log import debug, info, banner, warning


class RPMPackageManager:

    def load_json(filepath: str) -> Dict[str, List[str]]:
        """Load JSON file and return as dictionary."""
        with open(filepath, 'r') as f:
            return json.load(f)

    def build_provides_set(provides: Dict[str, List[str]]) -> Set[str]:
        """Build a set of all provided dependencies."""
        all_provides = set()
        for package, dependencies in provides.items():
            all_provides.update(dependencies)
        return all_provides

    def check_dependencies(file_path: str) -> Dict:
        """
        Check if all required dependencies are satisfied.
        Returns a dictionary with results.
        """
        requires_path = os.path.join(file_path, "requires.json")
        provides_path = os.path.join(file_path, "provides.json")
        
        requires = RPMPackageManager.load_json(requires_path)
        provides = RPMPackageManager.load_json(provides_path)
        provides_set = RPMPackageManager.build_provides_set(provides)
        
        results = {
            'satisfied': [],
            'missing': [],
            'packages_with_missing': {}
        }
    
        for package, dependencies in requires.items():
            package_missing = []
            debug(f"Checking dependencies for package: {package}")
        
            for dep in dependencies:
                if dep.startswith('rpmlib('):
                    continue
            
                if dep not in provides_set:
                    debug(f"  [MISSING] {dep}")
                    package_missing.append(dep)
                    results['missing'].append({
                        'package': package,
                        'dependency': dep
                    })
                else:
                    debug(f"  [OK] {dep}")
                    results['satisfied'].append({
                        'package': package,
                        'dependency': dep
                    })
            
            if package_missing:
                results['packages_with_missing'][package] = package_missing
        
        if results['missing']:
            warning(f"Dependency Check Failed: {len(results['missing'])} missing dependencies found.")
            warning("\n" + "="*60)
            warning("❌ MISSING DEPENDENCIES")
            warning("="*60)
            for i, dep in enumerate(results['missing'], 1):
                if isinstance(dep, dict):
                    package = dep.get('package', 'Unknown')
                    dependency = dep.get('dependency', 'Unknown')
                    warning(f"\n{i}. 📦 {package}")
                    warning(f"   └─ Requires: {dependency}")
                else:
                    warning(f"\n{i}. ❌ {dep}")
            warning("="*60 + "\n")
        else:
            banner("Dependency Check Passed: All dependencies satisfied.")
    
        return results