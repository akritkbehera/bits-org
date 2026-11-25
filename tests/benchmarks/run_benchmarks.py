#!/usr/bin/env python3
"""Benchmark runner for the bits recipe resolution pipeline.

Defines workloads, runs each N times (fresh-process and in-process),
collects wall time, peak RSS, CPU time, and profiler data.  Saves raw
JSON results to the output directory.

Usage:
  python3 run_benchmarks.py --config-dir ~/Desktop/cms.bits \
      --out-dir /tmp/akbehera/opencode/prof/results \
      [--runs 10] [--venv .venv-profile]
"""
import argparse
import json
import os
import resource
import subprocess
import sys
import time
from statistics import mean, median, pstdev

# ── Workloads ────────────────────────────────────────────────────────────────
# Each workload: (name, packages, notes)
WORKLOADS = [
  ("W1_zlib",       "zlib",              "smallest closure, ~5 pkgs"),
  ("W2_Python",     "Python",            "small closure, ~19 pkgs"),
  ("W3_cmssw",      "cmssw",             "full CMSSW closure, ~844 pkgs"),
  ("W4_cmssw_coral","cmssw,coral",       "two targets with overlap"),
  ("W5_acts",       "acts",              "nested #!includes (5 in acts.sh)"),
]

# ── Child script: runs in a fresh process ───────────────────────────────────
CHILD_SCRIPT = r"""
import json, os, resource, sys, time

def main():
  config_dir = sys.argv[1]
  packages_csv = sys.argv[2]
  defaults = sys.argv[3]
  arch = sys.argv[4]
  profile = sys.argv[5]  # "on" or "off"

  # Set up sys.argv[0] for generated package generators
  bits_root = os.environ["BITS_ROOT"]
  sys.argv[0] = os.path.join(bits_root, "bits")
  pp = os.environ.get("PYTHONPATH", "")
  os.environ["PYTHONPATH"] = ":".join(
      x for x in ([bits_root] + ([pp] if pp else [])) if x)

  # Enable profiler if requested
  if profile == "on":
    os.environ["BITS_PROFILE_RECIPES"] = "1"
    os.environ["BITS_PROFILE_OUT"] = sys.argv[6]

  # Import after env is set up
  from bits_helpers.defaults import parseDefaults, readDefaults
  from bits_helpers.packages import getPackageList
  from bits_helpers.utilities import topological_sort

  class Args:
    def __init__(self, cd, ds, arch):
      self.configDir = cd
      self.defaults = ds
      self.architecture = arch
      self.disable = []
      self.flavours = {}

  args = Args(config_dir, [d for d in defaults.split("::") if d], arch)
  packages = [p for p in packages_csv.split(",") if p]

  # Measure the full resolution
  t0 = time.perf_counter_ns()

  (err, overrides, taps, defaultsMeta) = parseDefaults(
      args.disable,
      lambda: readDefaults(args.configDir, args.defaults, print, args.architecture),
      print, args.architecture, args.configDir)
  assert not err, err

  specs = {}
  systemPackages, ownPackages, failed, validDefaults = getPackageList(
      packages=packages, specs=specs, configDir=args.configDir,
      preferSystem=False, noSystem=None, architecture=args.architecture,
      disable=args.disable, force_rebuild=(), defaults=args.defaults,
      performPreferCheck=lambda *_: (1, ""),
      performRequirementCheck=lambda *_: (1, ""),
      performValidateDefaults=lambda spec: (True, "", ["release"]),
      overrides=overrides, taps=taps, log=lambda *_: None,
      provider_dirs={}, defaults_meta=defaultsMeta)

  buildOrder = list(topological_sort(specs))

  t1 = time.perf_counter_ns()
  wall_ns = t1 - t0

  # Resource usage
  ru = resource.getrusage(resource.RUSAGE_SELF)
  result = {
      "packages": len(specs),
      "order_len": len(buildOrder),
      "wall_ns": wall_ns,
      "peak_rss_kb": ru.ru_maxrss,
      "user_cpu_ns": int(ru.ru_utime * 1e9),
      "sys_cpu_ns": int(ru.ru_stime * 1e9),
  }
  json.dump(result, sys.stdout)

main()
"""


def run_child(bits_root, config_dir, packages_csv, defaults, arch,
              profile, profile_out, python, timeout=300):
  """Run the child script in a fresh process. Returns the result dict."""
  env = dict(os.environ)
  env["BITS_ROOT"] = bits_root
  env["PYTHONPATH"] = bits_root
  if profile == "on":
    env["BITS_PROFILE_RECIPES"] = "1"
    env["BITS_PROFILE_OUT"] = profile_out

  code = CHILD_SCRIPT
  args = [python, "-c", code, config_dir, packages_csv, defaults, arch,
          profile, profile_out or ""]

  t0 = time.perf_counter_ns()
  proc = subprocess.run(
      args, capture_output=True, text=True, env=env, timeout=timeout)
  wall_ns = time.perf_counter_ns() - t0

  if proc.returncode != 0:
    raise RuntimeError(
        "child failed (rc=%d)\nstdout: %s\nstderr: %s" %
        (proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:]))

  result = json.loads(proc.stdout)
  result["wall_ns_incl_startup"] = wall_ns
  return result


def run_benchmark(bits_root, config_dir, python, workload, runs,
                  out_dir, profile):
  """Run a single workload `runs` times. Returns list of result dicts."""
  name, packages_csv, notes = workload
  results = []
  for i in range(runs):
    profile_out = os.path.join(out_dir, "%s_run%d_profile.json" % (name, i)) \
        if profile else None
    r = run_child(bits_root, config_dir, packages_csv, "release",
                  "slc9_amd64_gcc14", profile, profile_out, python)
    r["run"] = i
    r["cold_fs"] = (i == 0)
    results.append(r)
    print("  %s run %d/%d: wall=%.3fs pkgs=%d" %
          (name, i + 1, runs, r["wall_ns"] / 1e9, r["packages"]))
  return results


def summarize(name, results):
  """Compute statistics for a list of result dicts."""
  walls = [r["wall_ns"] for r in results]
  walls_incl = [r["wall_ns_incl_startup"] for r in results]
  cold = [r for r in results if r["cold_fs"]]
  warm = [r for r in results if not r["cold_fs"]]

  def stats(vals):
    if not vals:
      return {}
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    p95_idx = int(0.95 * (n - 1))
    return {
      "count": n,
      "mean_ns": int(mean(vals)),
      "median_ns": int(median(vals)),
      "min_ns": vals_sorted[0],
      "max_ns": vals_sorted[-1],
      "p95_ns": vals_sorted[p95_idx],
      "stddev_ns": int(pstdev(vals)) if n > 1 else 0,
    }

  return {
    "workload": name,
    "packages": results[0]["packages"] if results else 0,
    "all": stats(walls),
    "all_incl_startup": stats(walls_incl),
    "cold": stats([r["wall_ns"] for r in cold]),
    "warm": stats([r["wall_ns"] for r in warm]),
    "peak_rss_kb_mean": int(mean(r["peak_rss_kb"] for r in results)),
    "user_cpu_ns_mean": int(mean(r["user_cpu_ns"] for r in results)),
    "sys_cpu_ns_mean": int(mean(r["sys_cpu_ns"] for r in results)),
  }


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--config-dir", required=True)
  ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
  ap.add_argument("--runs", type=int, default=10)
  ap.add_argument("--python", default=None,
                  help="python interpreter to use (default: .venv-profile/bin/python)")
  ap.add_argument("--workloads", default=None,
                  help="comma-separated workload names (default: all)")
  ap.add_argument("--profile", choices=["on", "off"], default="on",
                  help="enable/disable the recipe profiler")
  args = ap.parse_args()

  bits_root = os.path.dirname(os.path.dirname(
      os.path.abspath(__import__("bits_helpers").__file__)))
  python = args.python or os.path.join(bits_root, ".venv-profile", "bin", "python")

  os.makedirs(args.out_dir, exist_ok=True)
  all_results = {}
  summaries = {}

  selected = WORKLOADS
  if args.workloads:
    wanted = set(args.workloads.split(","))
    selected = [w for w in WORKLOADS if w[0] in wanted]

  for wl in selected:
    name = wl[0]
    print("=== %s: %s (%s) ===" % (name, wl[2], wl[1]))
    results = run_benchmark(bits_root, args.config_dir, python, wl,
                            args.runs, args.out_dir, args.profile)
    all_results[name] = results
    summaries[name] = summarize(name, results)
    s = summaries[name]
    print("  summary: median=%.3fs mean=%.3fs p95=%.3fs cold=%.3fs warm=%.3fs" % (
        s["all"]["median_ns"] / 1e9, s["all"]["mean_ns"] / 1e9,
        s["all"]["p95_ns"] / 1e9,
        s["cold"]["median_ns"] / 1e9 if s["cold"] else 0,
        s["warm"]["median_ns"] / 1e9 if s["warm"] else 0))

  # Save raw results
  raw_path = os.path.join(args.out_dir, "raw_results.json")
  with open(raw_path, "w") as f:
    json.dump({"workloads": all_results, "summaries": summaries,
               "config_dir": args.config_dir,
               "python": python,
               "profile": args.profile,
               "runs": args.runs,
               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
              f, indent=2)
  print("\nSaved raw results to %s" % raw_path)

  # Save profiler JSONs (already written by child processes)
  prof_files = [f for f in os.listdir(args.out_dir) if f.endswith("_profile.json")]
  if prof_files:
    print("Profiler files: %d" % len(prof_files))


if __name__ == "__main__":
  main()
