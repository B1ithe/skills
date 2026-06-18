#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 <mode> <inputDir> <outputDir> <classNameRegex>" >&2
  exit 1
fi

MODE="$1"
INPUT_DIR="$2"
OUTPUT_DIR="$3"
CLASS_NAME_REGEX="$4"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAR_PATH="$SCRIPT_DIR/JavaDecompiler-0.0.1.jar"

if [ ! -f "$JAR_PATH" ]; then
  echo "Decompiler JAR not found: $JAR_PATH" >&2
  exit 1
fi

if command -v jenv >/dev/null 2>&1; then
  jenv shell 21.0 >/dev/null
fi

exec java -jar "$JAR_PATH" "-m=$MODE" "$INPUT_DIR" "$OUTPUT_DIR" "$CLASS_NAME_REGEX"
