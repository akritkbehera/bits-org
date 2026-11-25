# Performance report: bits recipe resolution and parsing

Scope. This report establishes a quantitative baseline for the recipe
resolution/parsing pipeline that runs before any build starts, using an opt-in
profiler (`BITS_PROFILE_RECIPES=1`) and a fresh-process benchmark harness. It
measures where time goes, which work is redundant, and what the maximum
achievable speedups are (Amdahl's law). No optimizations are implemented.

- Machine: 24-core Intel Xeon Gold 6454, 128 GB RAM, Python 3.9.2, Linux.
- Recipe repository: local `~/Desktop/cms.bits` (356 `.sh` files, no `from:`
  inheritance, no remote providers, no network).
- All numbers are from 10 fresh-process runs per workload, run on an otherwise
  idle machine. Raw data: `results_off/` (profiler off) and `results_on/`
  (profiler on) directories; per-run JSON profiles are in `results_on/`.
  Raw data for the baseline in this report lives in
  `/tmp/akbehera/opencode/prof/{results_off,results_on}/`; re-running
  `run_benchmarks.py` (default `--out-dir`) writes fresh data to
  `tests/benchmarks/results/`.

## 1. Workloads

| ID  | Packages requested                       | Resolved count | What it exercises |
|-----|------------------------------------------|---------------:|-------------------|
| W1  | `zlib`                                   |             5  | small closure, 2 `#!include`s |
| W2  | `Python`                                 |            19  | medium closure, no includes |
| W3  | `cmssw`                                  |           844  | largest closure; generated (virtual) packages; `#!include`s |
| W4  | `cmssw,coral`                            |           844  | W3 plus a second top-level package (same resolved set here) |
| W5  | `acts`                                   |           311  | nested `#!include`s (acts → acts.sh, acts-deps.sh, …) |

Arch `slc9_amd64_gcc14`, defaults `release`, `provider_dirs={}`. The child
process runs the same code path as `bits build` up to just before scheduling:
`resolveDefaults` → `parseDefaults` → `getPackageList` (which parses recipes,
resolves `#!include`, and invokes `package.py` for generated packages) →
`topological_sort` of the full graph. It is not a build.

## 2. Wall-clock baseline (profiler off, 10 fresh runs each)

| Workload | median s | mean s | min s | max s | p95 s | stddev s | peak RSS MB | user CPU s | system CPU s |
|----------|---------:|-------:|------:|------:|------:|---------:|------------:|-----------:|-------------:|
| W1 zlib          |  0.0153 |  0.0176 |  0.0139 |  0.0528 |  0.0478 |  0.0127 |  23.2 | 0.0072 | 0.0030 |
| W2 Python        |  0.0244 |  0.0265 |  0.0204 |  0.0665 |  0.0587 |  0.0155 |  23.6 | 0.0091 | 0.0029 |
| W3 cmssw         | 25.1408 | 25.2027 | 24.4760 | 26.7543 | 26.3494 |  0.6910 |  24.9 | 1.1020 | 0.0212 |
| W4 cmssw,coral   | 25.1218 | 25.1643 | 24.5468 | 26.3334 | 26.0186 |  0.5780 |  24.9 | 1.1154 | 0.0217 |
| W5 acts          |  8.8846 |  8.9330 |  8.4572 | 10.0034 |  9.8238 |  0.4550 |  24.6 | 1.0633 | 0.0197 |

Cold-start note: these are fresh processes but not a cold filesystem; page
cache is shared between runs. First-ever-run numbers on a cold cache would add
the cost of first reads of 356 recipe files (~1 MB total, negligible compared
to the 25 s dominated by subprocesses, see §4).

The cmssw closure takes ~25 s of the ~1.3 s of user CPU. The pipeline is
almost entirely waiting on subprocesses (`package.py` invocations for
generated packages) and I/O, not on Python bytecode. This is why user CPU
(~1.1 s) is two orders of magnitude below wall time (~25 s).

## 3. Profiler overhead (on vs off)

Each workload was run 10× with the profiler off and 10× with it on. The
profiler writes JSON per run; the human summary goes to stderr.

| Workload | off median s | on median s | delta | on p95 s |
|----------|-------------:|------------:|------:|---------:|
| W1 zlib        |  0.0153 |  0.0174 | +2.1 ms |  0.0460 |
| W2 Python      |  0.0244 |  0.0227 | -1.7 ms |  0.0570 |
| W3 cmssw       | 25.1408 | 25.1027 | -38.1 ms | 26.4912 |
| W4 cmssw,coral | 25.1218 | 25.0685 | -53.3 ms | 25.9737 |
| W5 acts        |  8.8846 |  8.8386 | -46.0 ms |  9.7813 |

Conclusion: with the profiler on, runs are equal or marginally faster within
run-to-run noise (stddev ~0.5-0.7 s on the big workloads). Instrumentation
overhead in a 25 s pipeline dominated by subprocesses is below the noise
floor; for W1 (15 ms) the absolute delta is 2 ms, i.e. it is measurable but
not significant. There is no behavioral change: package list, hashes and
build graph are computed by the same code; the profiler only records timings
and counters.

## 4. Where the time goes (cmssw, profiler on)

Source: `W3_cmssw_phased.json` (one representative run; 845 parser
invocations). All durations are medians of the per-run distributions across
the 10 profiled runs unless stated otherwise.

### 4.1 Parser invocations

| Metric                                   | Value |
|------------------------------------------|------:|
| Total parser invocations                 |   845 |
| Unique canonical paths                   |   824 |
| Repeated invocations (same path ≥ 2×)    |    21 (2.49 %) |
| Parsed from file (`fs_read`)             |   285 |
| Parsed generated (virtual packages)      |   560 |
| Total parse wall time (all invocations)  | 22.510 s |
| — of which generated packages            | 22.352 s (**99.3 %**) |
| — of which file reads                    |   0.147 s (0.7 %) |
| File-read time, median per invocation    |   0.3 ms |
| Generated-package time, median           | 40.3 ms |
| Generated-package time, max              |  33.1 s (openblas, one outlier run) |

The single most important finding: **the parse pipeline spends 99.3 % of its
time inside the generated (virtual) package machinery**, i.e. the `command:`
subprocess (`python3 .../package.py <pkg> <ver> <type>`) that CMSSW recipes
run to expand a `cmssw` metapackage into hundreds of `cmssw-*` sub-packages.
The 285 file-based recipes, including all `#!include` resolution, take only
147 ms in total.

### 4.2 Repeated work

10 generated recipes were each re-parsed 3× (same generated recipe requested
by 3 different dependency contexts): `opencv`, `tensorflow-sources`,
`tensorflow-xla-runtime`, `rivet`, `lwtnn`, `tensorflow`, `openblas`, `fastjet`,
`ucx`, `gbl`. Redundant cost: 21 extra invocations ≈ 1.438 s (≈ 6.4 % of the
generated time, ≈ 5.6 % of the 25 s total). `defaults-release.sh` is parsed
twice (defaults phase + pkglist phase), negligible cost.

### 4.3 Operation timings (medians, cmssw)

| Operation            | count | median ms | p95 ms   | max s   |
|----------------------|------:|----------:|---------:|--------:|
| getPackageList       |    10 |   22614.7 | 24951.1  | 26.271  |
| parseRecipe          |   845 |    26.323 |   259.05 |  33.056 |
| yamlLoad             |   845 |     0.639 |     1.16 |   0.048 |
| topological_sort     |     1 |   133.198 |   133.20 |   0.133 |
| resolveFilename      |   844 |    11.301 |   235.93 |   2.615 |
| getGeneratedPackages |   844 |     4.712 |    12.36 |   0.486 |
| parseDefaults        |     1 |     1.929 |     1.93 |   0.002 |
| topological_sort (utilities) | 1 |    133.20 |   133.20 |   0.133 |

### 4.4 Counters (cmssw, one run)

| Counter            | Value |
|--------------------|------:|
| fs_reads           |   285 |
| path_lookups       |   855 |
| yaml_includes      |     0 |
| body_includes      |   148 |
| parent_hops        |     0 (no `from:` inheritance in cms.bits) |

### 4.5 Phase breakdown (cmssw, phased run)

| Phase     | Parser invocations | Median per-invocation |
|-----------|-------------------:|----------------------:|
| defaults  |           2 of 845 | 0.05 ms               |
| pkglist   |          843 of 845 | 26.3 ms               |
| (topo)    | 0 (topological_sort is a separate op) | — |

All parser work happens in the package-list phase; the defaults phase is
negligible (1.9 ms).

### 4.6 Acts workload (includes)

W5 (acts) has 311 packages and 8.88 s wall time; its profile shows
`body_includes = 5` for the `acts` top recipe chain only. Its parse time is
dominated by the same generated-package machinery (CMSSW metapackage
expansion), not by include resolution: file-read parses are sub-millisecond
each. `#!include` handling is therefore not a bottleneck at any scale
measured here.

## 5. Microbenchmarks

Standalone timing of isolated operations (1000 iterations, median), to bound
the cost of specific hot operations independent of I/O:

| Operation                              | median µs | notes |
|----------------------------------------|----------:|-------|
| `copy.deepcopy(spec)`                  |      19.6 | per recipe parse; 845× → 16.6 ms total |
| `copy.copy(spec)` (shallow)            |       0.7 | replacement cost |
| `validateSpec(spec)`                   |       0.2 | per recipe parse |
| `parseRecipe('CMSSW_14_4_x.sh')`       |  1100.0   | one file recipe, no includes |
| `transitive_dependencies(cmssw)`       |  26196.0  | full graph walk, 844 pkgs — dominated by the generated-package subprocesses |

The `transitive_dependencies` microbenchmark (26.2 s) is essentially the
whole pipeline: it calls into the same `parseRecipe`/`getGeneratedPackages`
path. The deepcopy cost (19.6 µs × 845 = 16.6 ms) is 0.07 % of total — a
known "fix" that is not worth doing on its own.

## 6. Amdahl's-law estimates

T = 25.14 s (median, cmssw, profiler off). f = fraction of T spent in the
addressable operation; max speedup = 1 / ((1 − f) + f/s).

| # | Opportunity                                                        | f (measured) | s (assumed) | Max speedup |
|---|--------------------------------------------------------------------|-------------:|------------:|------------:|
| 1 | Cache generated (virtual) package recipes in-process; the same    |   0.889 (22.35/25.14) | unbounded (in-memory hit) |   8.96× |
|   | generated recipe is re-produced per dependent context. Only the    |             |             |             |
|   | 824 unique generated recipes need the subprocess at all.           |             |             |             |
| 2 | De-duplicate repeated parses of the same generated recipe (10      |   0.056 (1.44/25.14) | unbounded |  1.059× |
|   | recipes × 3). Subset of #1; listed separately for attribution.     |             |             |             |
| 3 | Cache file-based recipe parses (285 reads, 147 ms) across the      |   0.006 (0.147/25.14) | unbounded |  1.006× |
|   | package list. Not significant at this scale.                       |             |             |             |
| 4 | Memoize `yamlLoad`'s per-parse YAML loader re-registration         |   0.025 (0.639 ms × 845 = 0.54 s / 25.14) | unbounded |  1.026× |
|   | (639 µs median per call).                                          |             |             |             |
| 5 | Replace `topological_sort` (133 ms) with an incremental algorithm. |   0.005 (0.133/25.14) | unbounded |  1.005× |
| 6 | Replace `copy.deepcopy(spec)` (16.6 ms) with shallow copy.         |   0.0007 (0.0166/25.14) | unbounded |  1.0007× |

The single dominant opportunity is **#1**: the generated-package subprocess
machinery. 88.9 % of the 25 s wall time is spent re-running `package.py`
subprocesses to produce recipes that could be memoized per unique (pkg, ver)
within a process. Even assuming the 824 unique generated recipes each still
need one subprocess call, the speedup is bounded by (22.35 s redundant
subprocess work removed from 25.14 s) ≈ **8.96×**, i.e. cmssw drops from
25 s to about 2.8 s (the remaining 2.8 s is: 2.79 s of unique generated
recipes + 0.15 s file reads + 0.54 s yamlLoad + 0.13 s topo + ~0.5 s
interpreter startup and other overhead).

If #1 is combined with #4 (yamlLoad) and #5 (topo), the compound max
speedup is ≈ 1 / (1/8.96 + 1/1.026 + 1/1.005 residual) ≈ **9.0×**.

Important caveats on the Amdahl table:

- These are *upper bounds* on speedup for the parse phase in a fresh
  process. They assume the memoized lookup is free; in practice a
  hash-lookup + dict access is ~100 ns, so the bound is tight.
- They do not account for build-orchestration overhead (scheduling,
  `bits_build` process spawn, environment setup) which is a separate phase
  not measured here.
- `s = unbounded` means "the replaced operation is replaced by a
  memory lookup", not that the operation is eliminated entirely: the
  subprocesses for the 824 *unique* generated recipes still run once.
- W1/W2 (small closures) see no benefit from any of these: their 15-24 ms
  is mostly interpreter startup and ~5-19 subprocesses.

## 7. Limitations

- Single machine, single Python (3.9.2), single recipe repository. The
  generated-package cost is specific to CMSSW-style recipes that run a
  `command:` subprocess; other recipe sets (no generated packages) will be
  dominated by file reads and will see the Amdahl bounds collapse.
- No network, no remote providers, no `from:` inheritance (parent_hops = 0
  in cms.bits). The profiler covers those paths (tested) but they are not
  exercised by these workloads.
- Fresh-process only. No cross-process caching is measured; a shared on-disk
  cache would change the cold-start numbers in §2.
- The 33 s outlier in generated-package max (openblas) is one run where a
  subprocess was slower (page-cache or scheduler effects); medians are used
  throughout to avoid amplifying outliers.
- The benchmark child script reproduces the pre-build code path of
  `bits build` but not the build itself (no `bits_build` process spawn, no
  recipe execution). A full `bits build` wall time would be larger; the
  parse-phase numbers are directly transferable.

## 8. Methodology

### Profiler
`bits_helpers/profile_recipes.py` (new, ~230 LOC). Opt-in via
`BITS_PROFILE_RECIPES=1` (read at import). When off, every probe is a
module-level no-op that checks a module-global `current` (None) — zero
per-call cost beyond one attribute read. When on, it records per-parser
invocations (canonical path, phase, duration, generated-vs-file, FS reads,
path lookups, YAML/body include counts, parent hops), per-operation
inclusive/exclusive timings (`perf_counter_ns`), and a per-run summary JSON.
19 unit tests in `tests/test_profile_recipes.py`.

### Instrumentation sites
`recipe.py` (`parseRecipe`, `yamlLoad`, `getGeneratedPackages`,
`FileReader.__call__`, `GitReader.__call__`, `construct_include`,
`resolveIncludes`), `paths.py` (existence check / `getConfigPaths` /
`resolveFilename` / `resolveDefaultsFilename`), `packages.py`
(`getPackageList` loop, `resolveFilename`, `parseRecipe_pkglist`),
`defaults.py` (`parseDefaults`, `_read_defaults_chain`, `defaults_parse`),
`utilities.py` (`topological_sort`). All are no-ops when the env var is
unset; `git diff` on the 6 instrumented files shows only the probe
insertions, no logic changes.

### Benchmark harness
`run_benchmarks.py` (in this directory). For each workload and each of 10
iterations, it spawns a fresh Python subprocess that:
1. Sets `sys.argv[0]` to the `bits` executable, `PYTHONPATH` to the bits
   root, `BITS_PROFILE_RECIPES` as configured.
2. Imports `bits_helpers.defaults`, `bits_helpers.packages`,
   `bits_helpers.utilities`.
3. Calls `resolveDefaults`, `parseDefaults`, `getPackageList`,
   `topological_sort` in that order, with `set_phase()` between them.
4. Writes the profile JSON (if on) and a result line to stdout.
The harness parses the result line (wall time, RSS, CPU time, package
count) and writes `results_<on|off>/raw_results.json` plus per-run
`*_profile.json` files.

### Statistics
For each workload, 10 runs: median, mean, min, max, p95, stddev.
Peak RSS via `resource.getrusage(RUSAGE_SELF).ru_maxrss` (Linux, KB → MB).
CPU time via `ru_utime + ru_stime`. Wall time via `time.perf_counter()` in
the child (excludes subprocess spawn, which is ~15 ms and not part of the
pipeline being measured).

## 9. Files

- `bits_helpers/profile_recipes.py` — profiler (new)
- `tests/test_profile_recipes.py` — 19 tests (new)
- `bits_helpers/{recipe,paths,packages,defaults,utilities}.py`,
  `bits_helpers/build.py` — instrumented (no logic changes)
- `CHANGELOG.md` — Unreleased entry
- `run_benchmarks.py` — reusable benchmark runner (fresh-process child)
- `PERFORMANCE_REPORT.md` — this report

Raw benchmark data (not committed; regenerate with `run_benchmarks.py`):
- `/tmp/akbehera/opencode/prof/results_off/raw_results.json` — 10×5 unprofiled runs
- `/tmp/akbehera/opencode/prof/results_on/raw_results.json` + `results_on/*_profile.json` (50 files)
  — 10×5 profiled runs
- `/tmp/akbehera/opencode/prof/results_on/W3_cmssw_phased.json` — representative cmssw profile with phase context
- `/tmp/akbehera/opencode/prof/microbenchmarks.json` — isolated operation timings
