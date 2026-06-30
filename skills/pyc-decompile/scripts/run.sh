#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
ENGINES_DIR="$SKILL_DIR/engines"
VALIDATORS_DIR="$SKILL_DIR/validators"
IMAGE_PREFIX="pyc-decompile"
ALL_ENGINES="uncompyle2 uncompyle6 decompyle3 pycdc depyo"

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
validator_image_name() { echo "${IMAGE_PREFIX}:validator"; }

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

py_rel_for_source() {
  local rel="$1"
  case "$rel" in
    *.pyo) echo "${rel%.pyo}.py" ;;
    *)     echo "${rel%.pyc}.py" ;;
  esac
}

candidate_rel_for_engine() {
  local rel="$1"
  local engine="$2"
  local py_rel dir base
  py_rel=$(py_rel_for_source "$rel")
  dir=$(dirname "$py_rel")
  base=$(basename "$py_rel" .py)
  if [ "$dir" = "." ]; then
    echo "${base}-${engine}.py"
  else
    echo "$dir/${base}-${engine}.py"
  fi
}

list_contains_exact() {
  local needle="$1"
  local haystack="$2"
  [ -f "$haystack" ] && grep -Fxq -- "$needle" "$haystack"
}

version_for_rel() {
  local rel="$1"
  local version_file="$2"
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local ver="${line%% *}"
    local item="${line#* }"
    if [ "$item" = "$rel" ]; then
      echo "$ver"
      return 0
    fi
  done < "$version_file"
  echo "unknown"
}

has_decompiler_error_markers() {
  local py_file="$1"
  grep -Eq "Parse error at or near|Syntax error at or near|Unsupported Python version|Unsupported opcode|Unsupported bytecode|Unknown opcode|Decompiler error|decompilation failed|failed to decompile" "$py_file"
}

ensure_image() {
  local label="$1"
  local img="$2"
  local context="$3"
  if docker image inspect "$img" >/dev/null 2>&1; then
    return 0
  fi

  echo "[$label] image not found: $img"
  echo -n "Build it now? [y/N/skip]: "
  read -r answer
  case "$answer" in
    y|Y|yes) docker build -t "$img" "$context" >&2 ;;
    skip|s) echo "[$label] skipped by user"; return 1 ;;
    *) echo "[$label] aborting batch"; exit 1 ;;
  esac
}

ensure_validator_image() {
  local img
  img=$(validator_image_name)
  if [ -n "${VALIDATOR_SKIP_FILE:-}" ] && [ -f "$VALIDATOR_SKIP_FILE" ]; then
    return 1
  fi
  if ensure_image "validator" "$img" "$VALIDATORS_DIR/python"; then
    return 0
  fi
  [ -n "${VALIDATOR_SKIP_FILE:-}" ] && : > "$VALIDATOR_SKIP_FILE"
  return 1
}

syntax_partial_results() {
  local requests="$1"
  local result="$2"
  local reason="$3"
  while IFS=$'\t' read -r _ver rel _py_rel; do
    [ -z "$rel" ] && continue
    printf 'PARTIAL\t%s\tsyntax=%s\n' "$rel" "$reason" >> "$result"
  done < "$requests"
}

run_syntax_validation() {
  local requests="$1"
  local root="$2"
  local result="$3"
  : > "$result"
  [ -s "$requests" ] || return 0

  local img
  img=$(validator_image_name)
  if ensure_validator_image; then
    if ! docker run --rm \
      -v "$requests:/requests.tsv:ro" \
      -v "$root:/candidate:ro" \
      "$img" /requests.tsv /candidate \
      > "$result" 2>&1; then
      : > "$result"
      syntax_partial_results "$requests" "$result" "validator-error"
    fi
  else
    syntax_partial_results "$requests" "$result" "validator-skipped"
  fi
}

# ── Subcommand: build ─────────────────────────────────────────────

cmd_build() {
  echo "Building engine Docker images..."
  for engine in $ALL_ENGINES; do
    local img
    img=$(image_name "$engine")
    echo "  [$engine] building $img ..."
    docker build -t "$img" "$ENGINES_DIR/$engine" >&2
    echo "  [$engine] done"
  done

  local validator_img
  validator_img=$(validator_image_name)
  echo "  [validator] building $validator_img ..."
  docker build -t "$validator_img" "$VALIDATORS_DIR/python" >&2
  echo "  [validator] done"
  echo "All images built."
}

# ── Subcommand: engines ───────────────────────────────────────────

cmd_engines() {
  printf "%-14s %-10s %s\n" "ENGINE" "STATUS" "COVERS"
  printf "%-14s %-10s %s\n" "------" "------" "------"
  for engine in $ALL_ENGINES; do
    local img status
    img=$(image_name "$engine")
    if docker image inspect "$img" >/dev/null 2>&1; then
      status="ready"
    else
      status="missing"
    fi
    printf "%-14s %-10s %s\n" "$engine" "$status" "$(engine_versions "$engine")"
  done

  echo ""
  printf "%-14s %-10s %s\n" "VALIDATOR" "STATUS" "PYTHON"
  printf "%-14s %-10s %s\n" "---------" "------" "------"
  local validator_img validator_status
  validator_img=$(validator_image_name)
  if docker image inspect "$validator_img" >/dev/null 2>&1; then
    validator_status="ready"
  else
    validator_status="missing"
  fi
  printf "%-14s %-10s %s\n" "validator" "$validator_status" "2.7, 3.8, 3.11, 3.12, 3.14 when available"
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
  local copied_non_pyc="$work_dir/copied_non_pyc.txt"
  : > "$copied_non_pyc"

  # ── Phase 1: Copy non-pyc/pyo files as-is ───────────────────────
  echo "=== Phase 1: Copying non-pyc files ==="
  while IFS= read -r -d '' f; do
    local rel="${f#$input_dir/}"
    mkdir -p "$output_dir/$(dirname "$rel")"
    cp "$f" "$output_dir/$rel"
    echo "$rel" >> "$copied_non_pyc"
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

  local selected_dir="$work_dir/selected"
  local partial_dir="$work_dir/partials"
  local perfect_rels="$work_dir/perfect_rels.txt"
  local perfect_details="$work_dir/perfect_details.tsv"
  local partial_details="$work_dir/partial_details.tsv"
  local fail_details="$work_dir/fail_details.tsv"
  local VALIDATOR_SKIP_FILE="$work_dir/validator_skipped"
  mkdir -p "$selected_dir" "$partial_dir"
  : > "$perfect_rels"
  : > "$perfect_details"
  : > "$partial_details"
  : > "$fail_details"

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

  record_perfect() {
    local rel="$1"
    local engine="$2"
    local py_out="$3"
    local detail="$4"
    local py_rel
    py_rel=$(py_rel_for_source "$rel")
    if list_contains_exact "$rel" "$perfect_rels"; then
      return 0
    fi
    mkdir -p "$selected_dir/$(dirname "$py_rel")"
    cp "$py_out" "$selected_dir/$py_rel"
    echo "$rel" >> "$perfect_rels"
    printf '%s\t%s\t%s\n' "$rel" "$engine" "$detail" >> "$perfect_details"
  }

  record_partial() {
    local rel="$1"
    local engine="$2"
    local py_out="$3"
    local reason="$4"
    local candidate
    candidate=$(candidate_rel_for_engine "$rel" "$engine")
    mkdir -p "$partial_dir/$(dirname "$candidate")"
    cp "$py_out" "$partial_dir/$candidate"
    printf '%s\t%s\t%s\t%s\n' "$rel" "$engine" "$candidate" "$reason" >> "$partial_details"
  }

  record_fail() {
    local rel="$1"
    local engine="$2"
    local reason="$3"
    printf '%s\t%s\t%s\n' "$rel" "$engine" "$reason" >> "$fail_details"
  }

  clear_generated_outputs() {
    local rel="$1"
    local py_rel candidate engine
    py_rel=$(py_rel_for_source "$rel")
    if ! list_contains_exact "$py_rel" "$copied_non_pyc"; then
      rm -f "$output_dir/$py_rel"
    fi
    for engine in $ALL_ENGINES; do
      candidate=$(candidate_rel_for_engine "$rel" "$engine")
      rm -f "$output_dir/$candidate"
    done
  }

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
        if ! list_contains_exact "$rel" "$perfect_rels"; then
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
    ensure_image "$engine" "$img" "$ENGINES_DIR/$engine" || continue

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
      -v "$ENGINES_DIR/$engine/decompile.sh:/decompile.sh:ro" \
      "$img" /input /output \
      > "$result" 2>&1 || true

    # Parse outputs, mark partials immediately, and batch syntax-check clean files.
    local perfect=0
    local partial=0
    local fail=0
    local validation_requests="$work_dir/validate_${engine}.tsv"
    local validation_result="$work_dir/validate_${engine}_result.tsv"
    : > "$validation_requests"
    : > "$validation_result"

    while IFS= read -r line; do
      case "$line" in
        "OK: "*)
          local ok_rel="${line#OK: }"
          local py_rel py_out ver
          py_rel=$(py_rel_for_source "$ok_rel")
          py_out="$eng_output/$py_rel"
          if [ -f "$py_out" ] && [ -s "$py_out" ]; then
            if has_decompiler_error_markers "$py_out"; then
              record_partial "$ok_rel" "$engine" "$py_out" "marker=decompiler-error"
              partial=$((partial + 1))
            else
              ver=$(version_for_rel "$ok_rel" "$version_files")
              printf '%s\t%s\t%s\n' "$ver" "$ok_rel" "$py_rel" >> "$validation_requests"
            fi
          else
            record_fail "$ok_rel" "$engine" "missing-output"
            fail=$((fail + 1))
          fi
          ;;
        "FAIL: "*)
          local fail_rel="${line#FAIL: }"
          record_fail "$fail_rel" "$engine" "engine-failed"
          fail=$((fail + 1))
          ;;
      esac
    done < "$result"

    run_syntax_validation "$validation_requests" "$eng_output" "$validation_result"
    while IFS=$'\t' read -r status rel detail; do
      [ -z "$status" ] && continue
      local py_rel py_out
      py_rel=$(py_rel_for_source "$rel")
      py_out="$eng_output/$py_rel"
      case "$status" in
        PERFECT)
          if [ -f "$py_out" ] && [ -s "$py_out" ]; then
            record_perfect "$rel" "$engine" "$py_out" "$detail"
            perfect=$((perfect + 1))
          else
            record_fail "$rel" "$engine" "missing-output"
            fail=$((fail + 1))
          fi
          ;;
        PARTIAL)
          if [ -f "$py_out" ] && [ -s "$py_out" ]; then
            record_partial "$rel" "$engine" "$py_out" "$detail"
            partial=$((partial + 1))
          else
            record_fail "$rel" "$engine" "missing-output"
            fail=$((fail + 1))
          fi
          ;;
        *)
          if [ -f "$py_out" ] && [ -s "$py_out" ]; then
            record_partial "$rel" "$engine" "$py_out" "syntax=unavailable:validator-output"
            partial=$((partial + 1))
          else
            record_fail "$rel" "$engine" "missing-output"
            fail=$((fail + 1))
          fi
          ;;
      esac
    done < "$validation_result"

    echo "[$engine] $perfect PERFECT, $partial PARTIAL, $fail FAIL"
  done

  # ── Phase 4: Select outputs and report ──────────────────────────
  echo "=== Phase 4: Selecting outputs and reporting ==="

  local report="$output_dir/.batch-report.txt"
  {
    echo "PYC Decompilation Report"
    echo "========================"
    echo ""
    echo "Input:  $input_dir"
    echo "Output: $output_dir"
    echo ""

    local ok_total=0
    local partial_total=0
    local partial_candidate_total=0
    local fail_total=0
    local skip_total=0

    while IFS= read -r line; do
      [ -z "$line" ] && continue
      local ver="${line%% *}"
      local rel="${line#* }"
      local py_rel
      py_rel=$(py_rel_for_source "$rel")
      clear_generated_outputs "$rel"

      if list_contains_exact "$rel" "$perfect_rels"; then
        local ok_engine=""
        local ok_detail=""
        while IFS=$'\t' read -r p_rel p_engine p_detail; do
          if [ "$p_rel" = "$rel" ]; then
            ok_engine="$p_engine"
            ok_detail="$p_detail"
            break
          fi
        done < "$perfect_details"

        mkdir -p "$output_dir/$(dirname "$py_rel")"
        cp "$selected_dir/$py_rel" "$output_dir/$py_rel"
        echo "OK: $py_rel (source: $rel, version: $ver, engine: $ok_engine, $ok_detail)"
        ok_total=$((ok_total + 1))
        continue
      fi

      local found_partial=0
      while IFS=$'\t' read -r p_rel p_engine p_candidate p_reason; do
        if [ "$p_rel" = "$rel" ]; then
          mkdir -p "$output_dir/$(dirname "$p_candidate")"
          cp "$partial_dir/$p_candidate" "$output_dir/$p_candidate"
          echo "PARTIAL: $p_candidate (source: $rel, version: $ver, engine: $p_engine, $p_reason)"
          found_partial=1
          partial_candidate_total=$((partial_candidate_total + 1))
        fi
      done < "$partial_details"

      if [ "$found_partial" -eq 1 ]; then
        partial_total=$((partial_total + 1))
      else
        echo "FAIL: $rel (version: $ver)"
        fail_total=$((fail_total + 1))
      fi
    done < "$version_files"

    echo ""
    echo "---"
    echo ""

    # Unknown files
    if [ -f "$unknown_list" ]; then
      while IFS= read -r rel; do
        [ -z "$rel" ] && continue
        echo "SKIP: $rel (unknown magic number)"
        skip_total=$((skip_total + 1))
      done < "$unknown_list"
    fi

    echo ""
    echo "Summary: $ok_total OK, $partial_total PARTIAL ($partial_candidate_total candidates), $fail_total FAIL, $skip_total SKIP"
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
