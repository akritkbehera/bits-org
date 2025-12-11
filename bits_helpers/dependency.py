import os
import platform
import subprocess
import shutil
import glob
from typing import Dict, List, Optional


class RPMPackageManager:
    def __init__(self, spec: Dict[str, str], config_dir: str, work_dir: str):
        self.global_provides: List[str] = []
        self.config_dir = config_dir
        self.work_dir = work_dir
        self.spec = spec

    def rpm_name(self, spec: Optional[Dict[str, str]] = None) -> str:
        s = spec or self.spec
        return f"{s['package']}_{s['version']}_{s['revision']}_{s['hash']}-1-1.{platform.machine()}.rpm"

    def rpm_path(self, spec: Optional[Dict[str, str]] = None) -> str:
        return os.path.join(
            self.work_dir,
            "rpmbuild",
            "RPMS",
            platform.machine(),
            self.rpm_name(spec or self.spec),
        )

    def _run_rpm_query(self, rpm_path: str, query_type: str) -> List[str]:
        if not os.path.isfile(rpm_path):
            print(f"Warning: RPM file not found: {rpm_path}")
            return []

        try:
            result = subprocess.run(
                ["rpm", "-qp", query_type, rpm_path],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout.strip():
                return [
                    ln.strip() for ln in result.stdout.strip().split("\n") if ln.strip()
                ]
            elif result.returncode != 0:
                print(f"RPM query failed (exit {result.returncode}): {result.stderr}")
            return []

        except subprocess.TimeoutExpired:
            print(f"Timeout querying {rpm_path}")
        except FileNotFoundError:
            print("Error: 'rpm' command not found. Is RPM installed?")
        except Exception as e:
            print(f"Error querying {rpm_path}: {e}")
        return []

    def get_package_provides(self, spec: Optional[Dict[str, str]] = None) -> List[str]:
        return self._run_rpm_query(self.rpm_path(spec or self.spec), "--provides")

    def get_package_requires(self, spec: Optional[Dict[str, str]] = None) -> List[str]:
        return self._run_rpm_query(self.rpm_path(spec or self.spec), "--requires")

    def _build_system_provides_rpm(self, spec_path: str) -> Optional[str]:
        specs_dir = os.path.join(self.work_dir, "rpmbuild", "SPECS")
        os.makedirs(specs_dir, exist_ok=True)

        dest = os.path.join(specs_dir, "system-provides.spec")
        try:
            shutil.copyfile(spec_path, dest)
        except Exception as e:
            print(f"Error copying spec file: {e}")
            return None

        try:
            result = subprocess.run(
                [
                    "rpmbuild",
                    "-bb",
                    "--define",
                    f"_topdir {os.path.join(self.work_dir, 'rpmbuild')}",
                    "--define",
                    f"_buildarch {platform.machine()}",
                    dest,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )

            if result.returncode != 0:
                print(f"RPM build failed (exit {result.returncode}):\n{result.stderr}")
                return None

            pattern = os.path.join(
                self.work_dir,
                "rpmbuild",
                "RPMS",
                platform.machine(),
                "system-provides-*.rpm",
            )
            rpms = glob.glob(pattern)

            if rpms:
                return rpms[0]
            print("Warning: RPM build succeeded but no RPM file found")
            return None

        except subprocess.TimeoutExpired:
            print("Error: RPM build timed out")
        except FileNotFoundError:
            print("Error: 'rpmbuild' command not found. Is RPM build tools installed?")
        except Exception as e:
            print(f"Error building system-provides RPM: {e}")
        return None

    def system_packages(self) -> bool:
        sys_rpm = os.path.join(
            self.work_dir, "rpmbuild", "RPMS", platform.machine(), "system-provides.rpm"
        )

        if os.path.exists(sys_rpm):
            print(f"Found existing system-provides RPM: {sys_rpm}")
            self.global_provides.extend(self.get_package_provides())
            return True

        bits_path = os.environ.get("BITS_PATH", "")
        if not bits_path:
            return False

        for bits in [p.strip() for p in bits_path.split(",") if p.strip()]:
            spec_path = os.path.join(
                self.config_dir, f"{bits}.bits", "system-provides.spec"
            )

            if not os.path.exists(spec_path):
                continue

            rpm = self._build_system_provides_rpm(spec_path)
            if rpm:
                self.global_provides.extend(self.get_package_provides())
                return True

        return False

    def _extract_package_name(self, req: str) -> str:
        for op in [">=", "<=", "=", ">", "<"]:
            if op in req:
                return req.split(op)[0].strip()
        return req.strip()

    def check_dependency(self, spec: Dict[str, str]):
        requires = self.get_package_requires(spec)
        self.global_provides.extend(self.get_package_provides(spec))

        missing = []
        for req in requires:
            if req.startswith("rpmlib("):
                continue

            base_req = self._extract_package_name(req)
            satisfied = any(
                base_req == self._extract_package_name(p) or req == p
                for p in self.global_provides
            )

            if not satisfied:
                missing.append(req)

        if missing:
            print("Missing", spec.get("package"), missing)

        return len(missing) == 0, missing