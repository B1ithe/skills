#!/bin/bash
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

decompile_one() {
    local input_dir="$1"
    local output_dir="$2"
    local pyc_file="$3"
    local rel_path="${pyc_file#$input_dir/}"
    local py_output
    if [[ "$rel_path" == *.pyo ]]; then
        py_output="$output_dir/${rel_path%.pyo}.py"
    else
        py_output="$output_dir/${rel_path%.pyc}.py"
    fi
    mkdir -p "$(dirname "$py_output")"
    if uncompyle6 -o "$(dirname "$py_output")" "$pyc_file" >/dev/null 2>/dev/null && [ -s "$py_output" ]; then
        echo "OK: $rel_path"
    else
        rm -f "$py_output"
        echo "FAIL: $rel_path"
    fi
}

if [ "${1:-}" = "--one" ]; then
    decompile_one "$2" "$3" "$4"
    exit 0
fi

INPUT_DIR="$1"
OUTPUT_DIR="$2"
JOBS="${3:-1}"
find "$INPUT_DIR" -type f \( -name "*.pyc" -o -name "*.pyo" \) -print0 \
    | xargs -0 -r -n 1 -P "$JOBS" "$SELF" --one "$INPUT_DIR" "$OUTPUT_DIR"
