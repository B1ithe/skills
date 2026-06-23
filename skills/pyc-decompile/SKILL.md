---
name: pyc-decompile
description: "Decompile Python .pyc and .pyo files into readable .py source code using 5 Docker-isolated decompiler engines (uncompyle2, uncompyle6, decompyle3, pycdc, depyo) with automatic engine chain fallback. Use this skill whenever the user wants to decompile, reverse-engineer, or view the source of compiled Python bytecode — whether it's a single .pyc file, a directory of them, or mixed with non-pyc files. Also trigger when the user mentions wanting to read or inspect a .pyc file, recover lost Python source, or reverse engineer a Python application. Even if the user doesn't say 'decompile' explicitly — phrases like 'show me what this pyc does', 'I need the source for this compiled Python file', or 'reverse engineer this Python bytecode' should trigger this skill."
---

# PYC Decompiler Skill

Decompile `.pyc` and `.pyo` files into readable `.py` source using a chain of Docker-isolated decompiler engines. Each engine runs in its own container with exactly the right runtime environment — no host-side Python/Node.js/C++ dependency.

## Engines

| Engine | Python Versions | Runtime |
|---|---|---|
| uncompyle2 | 2.7 | Python 2.7 |
| uncompyle6 | 1.0 – 3.8 | Python 3.8 |
| decompyle3 | 3.7 – 3.8 | Python 3.8 |
| pycdc | 1.0 – 3.14 | C++ (native) |
| depyo | 1.0 – 3.14 | Node.js |

Each engine has a known version coverage range. Files are routed to engines based on their Python version (detected from the magic number in the `.pyc` header). When the primary engine fails on a file, the next engine in the chain is tried automatically.

## Engine Chain (Version Routing)

| Python Version | Engine Chain (priority order) |
|---|---|
| 1.0 – 2.6 | uncompyle6 → depyo → pycdc |
| 2.7 | uncompyle2 → uncompyle6 → depyo → pycdc |
| 3.0 – 3.6 | uncompyle6 → depyo → pycdc |
| 3.7 – 3.8 | uncompyle6 → decompyle3 → depyo → pycdc |
| 3.9 – 3.14 | depyo → pycdc |
| Unrecognized | skipped, reported |

## Prerequisites

The only host-side dependency is **Docker**. No Python, Node.js, or C++ compiler is needed.

## Usage

All commands are run from the skill directory:

```bash
bash {SKILL_DIR}/scripts/run.sh <command> [args...]
```

### Commands

```bash
# Build all engine Docker images (required before first use)
bash {SKILL_DIR}/scripts/run.sh build

# List engine availability status
bash {SKILL_DIR}/scripts/run.sh engines

# Decompile a directory of .pyc files
bash {SKILL_DIR}/scripts/run.sh decompile <input_dir> <output_dir>
```

### Building Images

Before the first decompilation, build all engine images:

```bash
bash {SKILL_DIR}/scripts/run.sh build
```

This creates 5 Docker images: `pyc-decompile:uncompyle2`, `pyc-decompile:uncompyle6`, `pyc-decompile:decompyle3`, `pyc-decompile:pycdc`, `pyc-decompile:depyo`.

### Checking Engine Status

```bash
bash {SKILL_DIR}/scripts/run.sh engines
```

Shows which images are built (`ready`) and which are missing.

### Running a Batch Decompilation

```bash
bash {SKILL_DIR}/scripts/run.sh decompile ./input_dir ./output_dir
```

The command:
1. Copies non-`.pyc`/`.pyo` files as-is to output
2. Scans magic numbers in `.pyc`/`.pyo` files to detect Python versions
3. Routes each file through the appropriate engine chain
4. Engines run one at a time (serial), each processing its pending files
5. If an engine image is missing, prompts the user to build or skip
6. Failed files are retried with the next engine in chain
7. Produces a batch report at `.batch-report.txt` in the output directory

## Workflow

1. **Identify the input**: Determine the path to the `.pyc` file(s) or directory the user wants to decompile.

2. **Check engine availability**: Run `engines` to see which images are built. If images are missing, run `build` first (or the script will prompt during decompilation).

3. **Run decompilation**:
   ```bash
   bash {SKILL_DIR}/scripts/run.sh decompile /path/to/input /path/to/output
   ```

4. **Report results**: After decompilation completes, the batch report is printed to stdout and saved to `.batch-report.txt` in the output directory. Summarize the results for the user — how many files succeeded, failed, or were skipped.

## Output Structure

```
输入目录:                       输出目录:
├── utils.pyc          →       ├── utils.py          (反编译成功)
├── models.pyc         →       ├── models.py         (反编译成功)
├── broken.pyc         →       (失败，不出现在输出中)
├── data.json          →       ├── data.json         (原样复制)
└── lib/                       └── lib/
    └── helpers.pyc    →           └── helpers.py    (反编译成功)
                                  └── .batch-report.txt
```

- `.pyc`/`.pyo` files: decompiled to `.py`, preserving directory structure
- All other files: copied as-is
- Failed decompilations: absent from output, recorded in report
- Report: `.batch-report.txt` in output root

## Important Notes

- Only Docker is required on the host — no Python, Node.js, or C++ toolchain needed.
- Engine images are built once and reused; rebuild only when upstream tools update.
- If an engine image is missing at decompile time, the script prompts interactively (build / skip / abort).
- Unknown magic numbers (corrupted or non-standard `.pyc` files) are skipped and reported.
- Engine execution is serial — one container at a time — for predictable resource use.
- `.pyo` files are treated identically to `.pyc` files.
- Non-`.pyc`/`.pyo` files are copied as-is, not passed to any engine.
