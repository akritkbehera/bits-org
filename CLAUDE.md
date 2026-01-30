# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bits (package name: `bitsorg`) is a build tool for managing large software stacks, originating from aliBuild. It builds, installs, and packages software projects with complex dependency chains, primarily for the ALICE/ALFA physics communities. Python 3.6+, licensed GPLv3.

## Commands

### Testing
```bash
# Full test suite (Linux, requires network for git clones)
tox

# macOS-specific test suite
tox -e darwin

# Unit tests only (fast, no network needed)
python -m unittest discover tests/

# Single test file
python -m unittest tests/test_build.py

# With coverage
coverage run --source=. -m unittest discover tests/
```

### Installation
```bash
pip install -e .          # Development install
pip install -e .[docs]    # With documentation dependencies
```

### Documentation
```bash
cd docs && mkdocs serve
```

### Linting (currently commented out in tox.ini)
```bash
flake8 . --config .flake8
```

## Architecture

### Entry Points

- **`bitsBuild`** — Primary Python entry point. Parses CLI args via `bits_helpers/args.py`, then routes to action handlers (`build`, `init`, `clean`, `doctor`, `deps`, `version`, `architecture`).
- **`bits`** — Bash wrapper around `bitsBuild`. Adds module environment management (load/unload/enter/setenv/query) using the Environment Modules system. Reads config from `bits.rc`, `.bitsrc`, `~/.bitsrc`.
- **`bitsDoctor`**, **`bitsDeps`**, **`pb`** — Thin wrappers invoking specific functionality.

### Core Modules (`bits_helpers/`)

- **`build.py`** — Build orchestration. Parses recipe defaults, builds dependency graph, updates git repos in parallel, downloads sources, schedules builds, packages results, syncs to remote stores, and generates environment modulefiles.
- **`scheduler.py`** — Multi-threaded job scheduler with dependency resolution, priority queues, and resource management (CPU/memory limits).
- **`sync.py`** — Remote storage backends: HTTP/HTTPS, rsync, S3 (boto3), and CVMFS (read-only). Handles symlink/tarball management and multi-threaded upload/download.
- **`utilities.py`** — Recipe parsing (YAML-based package specs), defaults handling (deep merge), SHA256 hashing for package identity, topological sort for dependency ordering, architecture-specific path resolution, Jinja2 template expansion.
- **`git.py`** / **`sl.py`** — SCM implementations (Git and Sapling). Git supports reference caching, partial clones, and timeout management. Both extend the abstract base in `scm.py`.
- **`cmd.py`** — Subprocess wrappers with timeout and encoding fallback. Includes Docker container support for isolated builds.
- **`args.py`** — argparse-based CLI with subcommands and global/build-specific options.
- **`log.py`** — Custom log levels (BANNER=25, SUCCESS=45), color-coded TTY output.
- **`workarea.py`** — Development package initialization and git reference repo management.

### Build Flow

1. Parse CLI args and read defaults (release.sh, custom.sh)
2. Build dependency DAG from YAML package specs (recipes)
3. Update git repositories in parallel with retry logic
4. Download sources with resume capability
5. Schedule and execute build jobs respecting dependency order
6. Package results and sync to remote stores
7. Generate Environment Modules modulefiles

### Key Design Decisions

- Git is the only native source backend. Non-git sources should be imported into a git repository.
- Version managed by `setuptools_scm` (git tags), written to `bits_helpers/_version.py`.
- `build_template.sh` is the shell template executed for each package build.
- `tox.ini` sets `ARCHITECTURE` env var to control target platform (e.g., `slc7_x86-64`, `osx_x86-64`).
- Tests use `coverage` with branch coverage. The tox suite clones external repos from GitHub for integration tests.
