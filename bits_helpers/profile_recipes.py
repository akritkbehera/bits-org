# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""Opt-in profiling of the recipe resolution and parsing pipeline.

Enabled by ``BITS_PROFILE_RECIPES=1`` in the environment; completely inert
otherwise.  Records, per recipe parser invocation, the canonical recipe path,
the calling function / execution phase, parse duration, whether the recipe is
a generated package, the number of YAML ``!include`` / body ``#!include``
directives and ``from:`` parent hops, and the number of filesystem reads and
path lookup attempts.  It also records inclusive and exclusive timings for
each measured operation so that recursive calls (``from:`` chains, nested
``#!include``) do not inflate the totals.

No caching is implemented here; this module only observes.  Output is a
process-specific JSON file (``$BITS_PROFILE_OUT`` or
``/tmp/bits-recipe-profile-<pid>.json``) plus a human-readable summary on
stdout at ``atexit``.

Timings use ``time.perf_counter_ns()``.  The disabled path costs a single
module-attribute read per probe (no ``os.environ`` lookup, no import side
effect).  Measuring that overhead is part of the benchmark harness.
"""

import atexit
import json
import os
import sys
import time

ENV_VAR = "BITS_PROFILE_RECIPES"


def _out_path():
  p = os.environ.get("BITS_PROFILE_OUT")
  return p if p else "/tmp/bits-recipe-profile-%d.json" % os.getpid()


class _Timer:
  """Inclusive / exclusive operation timer over a parent stack.

  ``begin(name)`` pushes *name* and returns a timestamp; ``end(name, start)``
  pops it, records the elapsed time as inclusive for *name* and charges it to
  the exclusive bucket of the new stack top (the enclosing operation).  The
  resolution path is single-threaded and its recursion (``from:`` in
  ``parseRecipe``, nested ``#!include``) is sequential, so a single parent
  stack gives correct attribution: a node's ``exclusive_ns`` is the time spent
  in it with no child operation running, and ``inclusive_ns`` includes its
  children.  Values are ns.  A misbalanced begin/end is tolerated (the stack
  is clamped) so a profiled bug cannot take the build down.
  """
  def __init__(self):
    self.ops = {}   # name -> [count, inclusive_ns, exclusive_ns]
    self._stack = []

  def begin(self, name):
    rec = self.ops.get(name)
    if rec is None:
      rec = self.ops[name] = [0, 0, 0]
    rec[0] += 1
    self._stack.append(name)
    return time.perf_counter_ns()

  def end(self, name, start_ns):
    elapsed = time.perf_counter_ns() - start_ns
    rec = self.ops.get(name)
    if rec is None:
      # Misbalanced end for an unknown operation: drop the time rather than
      # crash the build over a profiling bug.
      return
    rec[1] += elapsed
    rec[2] += elapsed
    # Pop up to and including this node (tolerates a mismatched pop).
    while self._stack and self._stack[-1] != name:
      self._stack.pop()
    if self._stack:
      self._stack.pop()
    if self._stack:
      self.ops[self._stack[-1]][2] += elapsed

  def _ops_view(self):
    return {name: {"count": r[0], "inclusive_ns": r[1], "exclusive_ns": r[2]}
            for name, r in self.ops.items()}


class RecipeProfiler:
  """Collects recipe-parser invocation records and operation timings.

  A single instance per process.  All ``record_*`` and ``count`` calls are
  no-ops through the module-level ``current`` (None when disabled), which is
  the cheap disabled path the probes check."""
  def __init__(self, out_path=None):
    self.out_path = out_path or _out_path()
    self.started_ns = time.perf_counter_ns()
    self.invocations = []
    self.timer = _Timer()
    self.counters = {}

  def count(self, name, amount=1):
    self.counters[name] = self.counters.get(name, 0) + amount

  def counter_snapshot(self):
    return dict(self.counters)

  def counter_delta(self, before):
    d = {}
    for name, total in self.counters.items():
      b = before.get(name, 0)
      if total != b:
        d[name] = total - b
    for name in before:
      if name not in self.counters:
        d[name] = -before[name]
    return d

  def begin(self, name):
    return self.timer.begin(name)

  def end(self, name, start_ns):
    self.timer.end(name, start_ns)

  def record_invocation(self, *, recipe_path, phase, caller, duration_ns,
                        generated, yaml_includes, body_includes, parents,
                        fs_reads, path_lookups, parent_path=None, sha=None):
    rec = {
      "recipe": recipe_path,
      "phase": phase,
      "caller": caller,
      "duration_ns": duration_ns,
      "generated": bool(generated),
      "yaml_includes": int(yaml_includes or 0),
      "body_includes": int(body_includes or 0),
      "parents": int(parents or 0),
      "fs_reads": int(fs_reads or 0),
      "path_lookups": int(path_lookups or 0),
    }
    if parent_path is not None:
      rec["parent"] = parent_path
    if sha is not None:
      rec["sha"] = sha
    self.invocations.append(rec)

  def summary(self):
    invs = self.invocations
    total = len(invs)
    by_path = {}
    seen = set()
    repeated_ns = 0
    for inv in invs:
      k = inv["recipe"]
      d = by_path.setdefault(k, {"count": 0, "total_ns": 0,
                                 "generated": inv["generated"],
                                 "first_phase": inv["phase"],
                                 "sha": inv.get("sha")})
      d["count"] += 1
      d["total_ns"] += inv["duration_ns"]
      if inv.get("sha"):
        d["sha"] = inv["sha"]
      if k in seen:
        repeated_ns += inv["duration_ns"]
      else:
        seen.add(k)
    unique = len(by_path)
    repeated_parses = total - unique
    return {
      "total_invocations": total,
      "unique_recipes": unique,
      "repeated_parses": repeated_parses,
      "repeated_parse_pct": round(100.0 * repeated_parses / total, 2) if total else 0.0,
      "total_parse_ns": sum(i["duration_ns"] for i in invs),
      "repeated_parse_ns": repeated_ns,
      "per_recipe": {
        k: {
          "count": d["count"],
          "total_ns": d["total_ns"],
          "mean_ns": d["total_ns"] // d["count"] if d["count"] else 0,
          "generated": d["generated"],
          "phase": d["first_phase"],
          "sha": d.get("sha"),
        } for k, d in by_path.items()
      },
      "operations": self.timer._ops_view(),
      "counters": dict(self.counters),
    }

  def finish(self):
    s = self.summary()
    s["wall_ns"] = time.perf_counter_ns() - self.started_ns
    s["pid"] = os.getpid()
    s["out_path"] = self.out_path
    try:
      with open(self.out_path, "w") as f:
        json.dump({"summary": s,
                   "invocations": self.invocations,
                   "operations": s["operations"]}, f, indent=1)
    except OSError as e:
      print("bits recipe profiler: cannot write %s: %s" % (self.out_path, e),
            file=sys.stderr)
    _print_summary(s)


def _print_summary(s):
  print("", file=sys.stderr)
  print("=== bits recipe profiler ===", file=sys.stderr)
  print("parser invocations: %d (unique recipes: %d, repeated: %d, %.2f%%)" %
        (s["total_invocations"], s["unique_recipes"], s["repeated_parses"],
         s["repeated_parse_pct"]), file=sys.stderr)
  print("total parse time: %.3f ms   repeated-parse time: %.3f ms" %
        (s["total_parse_ns"] / 1e6, s["repeated_parse_ns"] / 1e6),
        file=sys.stderr)
  if s["operations"]:
    print("operations (count, inclusive, exclusive):", file=sys.stderr)
    for name in sorted(s["operations"],
                       key=lambda n: -s["operations"][n]["inclusive_ns"]):
      o = s["operations"][name]
      print("  %-34s %6d  %10.3f ms  %10.3f ms" %
            (name, o["count"], o["inclusive_ns"] / 1e6,
             o["exclusive_ns"] / 1e6), file=sys.stderr)
  if s["counters"]:
    print("counters:", file=sys.stderr)
    for name in sorted(s["counters"]):
      print("  %-34s %d" % (name, s["counters"][name]), file=sys.stderr)
  top = sorted(s["per_recipe"].items(), key=lambda kv: -kv[1]["total_ns"])[:10]
  if top:
    print("top recipes by cumulative parse time:", file=sys.stderr)
    for path, d in top:
      print("  %-48s %4d x  %10.3f ms  (%s)" %
            (path, d["count"], d["total_ns"] / 1e6,
             "generated" if d["generated"] else "file"), file=sys.stderr)
  print("profile: %s" % s["out_path"], file=sys.stderr)
  print("=== end bits recipe profiler ===", file=sys.stderr)


# Module-level probe state.  ``current`` is None when disabled; a probe calls
# ``current.<method>`` only after checking it, so the disabled cost is one
# attribute read.  ``_enabled`` mirrors the environment for the probes.
# The environment is read once at import time; the benchmark harness and the
# bits CLI entry point call ``set_enabled`` explicitly when they need to
# override it (e.g. for a test that flips the variable mid-process).
current = None
_enabled = os.environ.get(ENV_VAR) not in (None, "", "0", "false", "off")
if _enabled:
  current = RecipeProfiler()
  atexit.register(current.finish)


def _counter_snapshot():
  p = current
  return p.counter_snapshot() if p is not None else {}


def _counter_delta(before):
  p = current
  return p.counter_delta(before) if (p is not None and before) else {}


def _begin(name):
  p = current
  return p.begin(name) if p is not None else 0


def _end(name, start_ns):
  p = current
  if p is not None:
    p.end(name, start_ns)


def set_enabled(flag, out_path=None):
  """Enable or disable profiling in this process.  Returns the active
  profiler or None.  When flag is truthy a fresh profiler is created and
  registered with atexit; when falsy the current one (if any) is finished."""
  global current, _enabled
  if flag:
    if current is None:
      current = RecipeProfiler(out_path)
      atexit.register(current.finish)
    _enabled = True
    return current
  if current is not None:
    current.finish()
  current = None
  _enabled = False
  return None


def is_enabled():
  return _enabled is True


# ── Phase context ─────────────────────────────────────────────────────────
# The execution phase a probe is running in.  Set by the harness / build entry
# points; a probe records it on each invocation so the report can split
# provider-discovery parses from getPackageList parses from defaults parses.
_phase = "startup"


def set_phase(name):
  global _phase
  _phase = name


def get_phase():
  return _phase


# ── Counters the shared helpers increment ─────────────────────────────────
# paths.exists / paths.isfile / checkForFilename increment these; recipe.py
# increments the include counters.  When disabled they cost a single attribute
# read (current is None) and return immediately.

def _count(name, amount=1):
  p = current
  if p is not None:
    p.count(name, amount)


def count_path_lookup():
  _count("path_lookups")


def count_fs_read():
  _count("fs_reads")


def count_yaml_include():
  _count("yaml_includes")


def count_body_include():
  _count("body_includes")


def count_parent_hop():
  _count("parent_hops")
