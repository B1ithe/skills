#!/bin/bash
set -euo pipefail
INPUT_DIR="$1"
OUTPUT_DIR="$2"

find "$INPUT_DIR" -type f \( -name "*.pyc" -o -name "*.pyo" \) | while read pyc_file; do
    rel_path="${pyc_file#$INPUT_DIR/}"
    if [[ "$rel_path" == *.pyo ]]; then
        py_output="$OUTPUT_DIR/${rel_path%.pyo}.py"
    else
        py_output="$OUTPUT_DIR/${rel_path%.pyc}.py"
    fi
    mkdir -p "$(dirname "$py_output")"
    if uncompyle6 "$pyc_file" > "$py_output" 2>/dev/null && [ -s "$py_output" ]; then
        echo "OK: $rel_path"
    else
        rm -f "$py_output"
        echo "FAIL: $rel_path"
    fi
done
