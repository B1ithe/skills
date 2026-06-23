#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
ENGINES_DIR="$SKILL_DIR/engines"
IMAGE_PREFIX="pyc-decompile"

# ── Magic number → version lookup ──────────────────────────────────

magic_to_version() {
  case "$1" in
    20121) echo "1.5" ;;
    50428) echo "1.6" ;;
    50823) echo "2.0" ;;
    60202) echo "2.1" ;;
    60717) echo "2.2" ;;
    62011|62061|62071) echo "2.4" ;;
    62031) echo "2.3" ;;
    62131) echo "2.5" ;;
    62161) echo "2.6" ;;
    62211) echo "2.7" ;;
    3131) echo "3.0" ;;
    3151) echo "3.1" ;;
    3180) echo "3.2" ;;
    3230) echo "3.3" ;;
    3310) echo "3.4" ;;
    3350) echo "3.5" ;;
    3361|3379) echo "3.6" ;;
    3394) echo "3.7" ;;
    3413) echo "3.8" ;;
    3425) echo "3.9" ;;
    3439) echo "3.10" ;;
    3495) echo "3.11" ;;
    3531) echo "3.12" ;;
    3553|3571) echo "3.13" ;;
    3607) echo "3.14" ;;
    *) echo "unknown" ;;
  esac
}

# ── Engine version coverage lookup ─────────────────────────────────

engine_versions() {
  case "$1" in
    uncompyle2)  echo "2.7" ;;
    uncompyle6)  echo "1.0 1.5 1.6 2.0 2.1 2.2 2.3 2.4 2.5 2.6 2.7 3.0 3.1 3.2 3.3 3.4 3.5 3.6 3.7 3.8" ;;
    decompyle3)  echo "3.7 3.8" ;;
    pycdc)       echo "1.0 1.5 1.6 2.0 2.1 2.2 2.3 2.4 2.5 2.6 2.7 3.0 3.1 3.2 3.3 3.4 3.5 3.6 3.7 3.8 3.9 3.10 3.11 3.12 3.13 3.14" ;;
    depyo)       echo "1.0 1.5 1.6 2.0 2.1 2.2 2.3 2.4 2.5 2.6 2.7 3.0 3.1 3.2 3.3 3.4 3.5 3.6 3.7 3.8 3.9 3.10 3.11 3.12 3.13 3.14" ;;
  esac
}

# ── Version routing table lookup ───────────────────────────────────

version_chain() {
  case "$1" in
    1.0|1.5|1.6)                    echo "uncompyle6 depyo pycdc" ;;
    2.0|2.1|2.2|2.3|2.4|2.5|2.6)   echo "uncompyle6 depyo pycdc" ;;
    2.7)                             echo "uncompyle2 uncompyle6 depyo pycdc" ;;
    3.0|3.1|3.2|3.3|3.4|3.5|3.6)   echo "uncompyle6 depyo pycdc" ;;
    3.7|3.8)                         echo "uncompyle6 decompyle3 depyo pycdc" ;;
    3.9|3.10|3.11|3.12|3.13|3.14)   echo "depyo pycdc" ;;
    *)                               echo "" ;;
  esac
}

# ── Helpers ───────────────────────────────────────────────────────

image_name() { echo "${IMAGE_PREFIX}:$1"; }

engine_covers_version() {
  local wanted_ver="$2"
  for v in $(engine_versions "$1"); do
    [ "$v" = "$wanted_ver" ] && return 0
  done
  return 1
}

read_magic() {
  local file="$1"
  local magic
  magic=$(od -A n -t u2 -N 2 "$file" 2>/dev/null | tr -d ' ') || { echo "0"; return; }
  [ -z "$magic" ] && { echo "0"; return; }
  echo "$magic"
}

detect_version() {
  local magic
  magic=$(read_magic "$1")
  magic_to_version "$magic"
}

# ── Subcommand: build ─────────────────────────────────────────────

cmd_build() {
  echo "Building engine Docker images..."
  for engine in uncompyle2 uncompyle6 decompyle3 pycdc depyo; do
    local img
    img=$(image_name "$engine")
    echo "  [$engine] building $img ..."
    docker build -t "$img" "$ENGINES_DIR/$engine" >&2
    echo "  [$engine] done"
  done
  echo "All images built."
}

# ── Subcommand: engines ───────────────────────────────────────────

cmd_engines() {
  printf "%-14s %-10s %s\n" "ENGINE" "STATUS" "COVERS"
  printf "%-14s %-10s %s\n" "------" "------" "------"
  for engine in uncompyle2 uncompyle6 decompyle3 pycdc depyo; do
    local img status
    img=$(image_name "$engine")
    if docker image inspect "$img" >/dev/null 2>&1; then
      status="ready"
    else
      status="missing"
    fi
    printf "%-14s %-10s %s\n" "$engine" "$status" "$(engine_versions "$engine")"
  done
}

# ── Subcommand: decompile ─────────────────────────────────────────

cmd_decompile() {
  local input_dir="$1"
  local output_dir="$2"
  local engine_override="$3"  # optional: force a specific engine

  [ -d "$input_dir" ] || { echo "ERROR: input directory not found: $input_dir" >&2; exit 1; }
  mkdir -p "$output_dir"

  input_dir="$(cd "$input_dir" && pwd)"
  output_dir="$(cd "$output_dir" && pwd)"

  local work_dir
  work_dir="$(mktemp -d)"
  trap "rm -rf $work_dir" EXIT

  # ── Phase 1: Copy non-pyc/pyo files as-is ───────────────────────
  echo "=== Phase 1: Copying non-pyc files ==="
  while IFS= read -r -d '' f; do
    local rel="${f#$input_dir/}"
    mkdir -p "$output_dir/$(dirname "$rel")"
    cp "$f" "$output_dir/$rel"
  done < <(find "$input_dir" -type f ! -name "*.pyc" ! -name "*.pyo" -print0)

  # ── Phase 2: Scan magic numbers ─────────────────────────────────
  echo "=== Phase 2: Scanning versions ==="

  local version_files="$work_dir/version_files"
  local unknown_list="$work_dir/unknown_files"
  : > "$version_files"
  : > "$unknown_list"

  while IFS= read -r -d '' pyc; do
    local rel="${pyc#$input_dir/}"
    local ver
    ver=$(detect_version "$pyc")
    if [ "$ver" = "unknown" ]; then
      echo "UNKNOWN: $rel"
      echo "$rel" >> "$unknown_list"
    else
      echo "$ver $rel" >> "$version_files"
    fi
  done < <(find "$input_dir" -type f \( -name "*.pyc" -o -name "*.pyo" \) -print0)

  local total_unknown=0
  [ -f "$unknown_list" ] && total_unknown=$(wc -l < "$unknown_list" | tr -d ' ')
  echo "Version scan done. Unrecognized: $total_unknown"

  # ── Phase 3: Engine chain execution ─────────────────────────────
  echo "=== Phase 3: Decompilation ==="

  # Unique versions present
  local versions_present=""
  if [ -s "$version_files" ]; then
    versions_present=$(cut -d' ' -f1 "$version_files" | sort -u)
  fi

  # Collect all engines needed, in priority order (union across used versions)
  local all_engines=""
  if [ -n "$engine_override" ]; then
    all_engines="$engine_override"
    echo "Engine override: $engine_override (skipping version routing)"
  else
    for ver in $versions_present; do
      for eng in $(version_chain "$ver"); do
        case " $all_engines " in
          *" $eng "*) ;;
          *) all_engines="$all_engines $eng" ;;
        esac
      done
    done
    # Trim leading/trailing spaces
    all_engines="${all_engines# }"
    all_engines="${all_engines% }"
  fi

  # For each engine in order:
  for engine in $all_engines; do
    # Build list of files this engine should process
    local pending="$work_dir/pending_${engine}.txt"
    : > "$pending"

    local needs_image_check=0
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      local ver="${line%% *}"
      local rel="${line#* }"
      if [ -n "$engine_override" ] || engine_covers_version "$engine" "$ver"; then
        local expected
        case "$rel" in
          *.pyo) expected="${rel%.pyo}.py" ;;
          *)     expected="${rel%.pyc}.py" ;;
        esac
        if [ ! -f "$output_dir/$expected" ] || [ ! -s "$output_dir/$expected" ]; then
          echo "$rel" >> "$pending"
          needs_image_check=1
        fi
      fi
    done < "$version_files"

    if [ "$needs_image_check" -eq 0 ]; then
      echo "[$engine] no pending files, skipping"
      continue
    fi

    local pending_count
    pending_count=$(wc -l < "$pending" | tr -d ' ')
    echo "[$engine] $pending_count pending files"

    # Check / build image
    local img
    img=$(image_name "$engine")
    if ! docker image inspect "$img" >/dev/null 2>&1; then
      echo "[$engine] image not found: $img"
      echo -n "Build it now? [y/N/skip]: "
      read -r answer
      case "$answer" in
        y|Y|yes) docker build -t "$img" "$ENGINES_DIR/$engine" >&2 ;;
        skip|s) echo "[$engine] skipped by user"; continue ;;
        *) echo "[$engine] aborting batch"; exit 1 ;;
      esac
    fi

    # Stage only the files we need
    local staging="$work_dir/staging_${engine}"
    rm -rf "$staging"
    mkdir -p "$staging"
    while IFS= read -r rel; do
      [ -z "$rel" ] && continue
      mkdir -p "$staging/$(dirname "$rel")"
      cp "$input_dir/$rel" "$staging/$rel"
    done < "$pending"

    local eng_output="$work_dir/output_${engine}"
    mkdir -p "$eng_output"
    local result="$work_dir/result_${engine}.txt"

    docker run --rm \
      -v "$staging:/input:ro" \
      -v "$eng_output:/output" \
      "$img" /input /output \
      > "$result" 2>&1 || true

    # Parse and copy successful outputs
    local ok=0
    local fail=0
    while IFS= read -r line; do
      case "$line" in
        "OK: "*)
          ok=$((ok + 1))
          local ok_rel="${line#OK: }"
          local py_out
          case "$ok_rel" in
            *.pyo) py_out="$eng_output/${ok_rel%.pyo}.py" ;;
            *)     py_out="$eng_output/${ok_rel%.pyc}.py" ;;
          esac
          if [ -f "$py_out" ] && [ -s "$py_out" ]; then
            mkdir -p "$output_dir/$(dirname "$ok_rel")"
            local dest
            case "$ok_rel" in
              *.pyo) dest="$output_dir/${ok_rel%.pyo}.py" ;;
              *)     dest="$output_dir/${ok_rel%.pyc}.py" ;;
            esac
            cp "$py_out" "$dest"
          fi
          ;;
        "FAIL: "*)
          fail=$((fail + 1))
          ;;
      esac
    done < "$result"
    echo "[$engine] $ok OK, $fail FAIL"
  done

  # ── Phase 4: Batch report ───────────────────────────────────────
  echo "=== Phase 4: Report ==="

  local report="$output_dir/.batch-report.txt"
  {
    echo "PYC Decompilation Report"
    echo "========================"
    echo ""
    echo "Input:  $input_dir"
    echo "Output: $output_dir"
    echo ""

    local ok_total=0
    local fail_total=0

    # OK: .py files in output
    while IFS= read -r -d '' py; do
      local rel="${py#$output_dir/}"
      echo "OK: $rel"
      ok_total=$((ok_total + 1))
    done < <(find "$output_dir" -name "*.py" ! -name ".*" -print0)

    echo ""
    echo "---"
    echo ""

    # Failed: .pyc files without corresponding .py
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      local ver="${line%% *}"
      local rel="${line#* }"
      local expected
      case "$rel" in
        *.pyo) expected="${rel%.pyo}.py" ;;
        *)     expected="${rel%.pyc}.py" ;;
      esac
      if [ ! -f "$output_dir/$expected" ] || [ ! -s "$output_dir/$expected" ]; then
        echo "FAIL: $rel (version: $ver)"
        fail_total=$((fail_total + 1))
      fi
    done < "$version_files"

    # Unknown files
    if [ -f "$unknown_list" ]; then
      while IFS= read -r rel; do
        [ -z "$rel" ] && continue
        echo "SKIP: $rel (unknown magic number)"
        fail_total=$((fail_total + 1))
      done < "$unknown_list"
    fi

    echo ""
    echo "Summary: $ok_total OK, $fail_total FAIL/SKIP"
  } > "$report"

  cat "$report"
  echo ""
  echo "Report saved to $report"
}

# ── Main dispatch ─────────────────────────────────────────────────

usage() {
  echo "Usage: $0 <command> [args...]"
  echo ""
  echo "Commands:"
  echo "  build                  Build all engine Docker images"
  echo "  engines                List engine availability status"
  echo "  decompile [--engine <name>] <in> <out>"
  echo "                         Decompile .pyc files from input dir to output dir"
  echo "                         --engine: force a specific engine (skip version routing)"
  exit 1
}

case "${1:-}" in
  build)    cmd_build ;;
  engines)  cmd_engines ;;
  decompile)
    ENGINE_OVERRIDE=""
    INPUT_ARG=""
    OUTPUT_ARG=""
    while [ $# -gt 1 ]; do
      case "$2" in
        --engine)
          [ $# -lt 4 ] && { echo "ERROR: --engine requires a value" >&2; usage; }
          ENGINE_OVERRIDE="$3"
          shift 2
          ;;
        *)
          if [ -z "$INPUT_ARG" ]; then
            INPUT_ARG="$2"
          elif [ -z "$OUTPUT_ARG" ]; then
            OUTPUT_ARG="$2"
          else
            echo "ERROR: too many arguments" >&2; usage
          fi
          shift
          ;;
      esac
    done
    [ -n "$INPUT_ARG" ] && [ -n "$OUTPUT_ARG" ] || { echo "ERROR: decompile requires input and output directories" >&2; usage; }
    cmd_decompile "$INPUT_ARG" "$OUTPUT_ARG" "$ENGINE_OVERRIDE"
    ;;
  *) usage ;;
esac
