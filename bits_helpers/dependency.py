import subprocess
import os
import platform
import shutil
import glob


class RpmIndexer:
    global_provides = []
    
    def __init__(self, spec, configDir, work_dir):
        """
        Constructs the full path to the RPM based on spec and work_dir.
        """
        self.configDir = configDir
        self.work_dir = work_dir
        rpm_name = f"{spec['package']}_{spec['version']}_{spec['revision']}_{spec['hash']}-1-1.{platform.machine()}.rpm"
        self.rpm_path = os.path.join(work_dir, "rpmbuild", "RPMS", platform.machine(), rpm_name)
    
    def systemPackages(self):
        """
        Looks for system-provides.rpm or builds it from spec if needed.
        """
        system_rpm = os.path.join(self.work_dir, "rpmbuild", "RPMS", platform.machine(), "system-provides.rpm")
        if os.path.exists(system_rpm):
            self.getPackageProvides(system_rpm)
            return
        
        # Try to find and build system-provides.spec
        for p in os.environ.get("BITS_PATH", "").split(","):
            spec_path = os.path.join(self.configDir, str(p) + ".bits", "system-provides.spec")
            if os.path.exists(spec_path):
                dest = os.path.join(self.work_dir, "rpmbuild", "SPECS", "system-provides.spec")
                shutil.copyfile(spec_path, dest)
                cmd = [
                    "rpmbuild", "-bb",
                    "--define", "_topdir " + os.path.join(self.work_dir, "rpmbuild"),
                    os.path.join(self.work_dir, "rpmbuild", "SPECS", "system-provides.spec")
                ]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if result.returncode == 0:
                        # Find the built RPM using glob pattern
                        rpm_pattern = os.path.join(self.work_dir, "rpmbuild", "RPMS", 'noarch', "system-provides-*.rpm")
                        rpm_files = glob.glob(rpm_pattern)
                        if rpm_files:
                            self.getPackageProvides(rpm_files[0])
                            break
                except Exception as e:
                    print(f"Error building system-provides: {e}")
                    continue
    
    def getPackageProvides(self, rpm_path=None):
        """Runs rpm -qp --provides on rpm_path and updates global list."""
        if rpm_path is None:
            rpm_path = self.rpm_path
        
        cmd = ["rpm", "-qp", "--provides", rpm_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0 and result.stdout.strip():
                items = result.stdout.strip().split('\n')
                RpmIndexer.global_provides.extend(items)
        except Exception as e:
            print(f"Error getting provides from {rpm_path}: {e}")
    
    def getPackageRequires(self):
        """Runs rpm -qp --requires on self.rpm_path and returns list."""
        cmd = ["rpm", "-qp", "--requires", self.rpm_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split('\n')
        except Exception as e:
            print(f"Error getting requires from {self.rpm_path}: {e}")
        return []
    
    def checkDependency(self):
      """
      Registers this package's provides, then checks if its requirements 
      are met by the global list.
      """
      print("Current global provides:", RpmIndexer.global_provides)
      
      # 1. Register this package's provides
      self.getPackageProvides()
      
      # 2. Check if its requirements exist in the updated global list
      requires = self.getPackageRequires()
      
      # Use exact matching - no normalization needed
      provides_set = set(RpmIndexer.global_provides)
      
      missing = []
      for req in requires:
          # Skip rpmlib dependencies (internal RPM features)
          if req.startswith("rpmlib("):
              continue
          
          # Exact match
          if req not in provides_set:
              missing.append(req)
      
      # Returns True if missing list is empty, plus the list itself
      return (len(missing) == 0), missing