---
name: decompiler-java
description: "Decompile Java .class files and .jar archives into readable Java source code using the JavaDecompiler tool (supports Fernflower, CFR, and JADX engines). Use this skill whenever the user wants to decompile, reverse-engineer, or view the source of compiled Java bytecode — whether it's a single .class file, a .jar archive, or a directory full of them. Also trigger when the user mentions wanting to read or inspect a .class file, extract source from a JAR, or convert bytecode back to Java. Even if the user doesn't say 'decompile' explicitly — phrases like 'show me what this class does', 'I need the source for this JAR', or 'reverse engineer this library' should trigger this skill."
---

# Java Decompiler Skill

Decompile `.class` files and `.jar` archives into readable `.java` source files using the bundled JavaDecompiler tool.

## Tool Location

Use the bundled wrapper script:

```bash
{SKILL_DIR}/scripts/run-decompiler.sh
```

The script resolves the bundled JAR automatically from the skill directory.

## Prerequisites

The tool requires **Java 21 or higher**. Before running the decompiler, switch to the correct Java version:

```bash
jenv shell 21.0
```

Verify with `java -version` if needed. If `jenv` is not available, try `JAVA_HOME` or whatever Java version manager the user has.

## Usage

```bash
{SKILL_DIR}/scripts/run-decompiler.sh <mode> <inputDir> <outputDir> <classNameRegex>
```

### Arguments

| Argument | Description |
|---|---|
| `mode` | Decompiler engine: `fernflower` (default), `cfr`, or `jadx` |
| `inputDir` | Path to the input directory containing `.class` or `.jar` files |
| `outputDir` | Path where decompiled `.java` files will be written |
| `classNameRegex` | Java regex to filter which classes to decompile. Use `".*"` for all classes |

### Decompiler Engines

- **fernflower** — JetBrains' analytical decompiler. Good general-purpose default.
- **cfr** — Strong with modern Java features (lambdas, switch expressions, records).
- **jadx** — Originally designed for Android, also works well on regular JVM bytecode.

Default to `fernflower` unless the user specifies otherwise or a specific engine would be more appropriate.

## Workflow

1. **Identify the input**: Determine the path to the `.class` file, `.jar` file, or directory the user wants to decompile.

2. **Prepare the input directory**: The tool expects a directory as input, not a single file. If the user points to a single `.class` or `.jar` file, create a temporary input directory and copy/move the file into it:
   ```bash
   mkdir -p /tmp/decompile-input
   cp /path/to/SomeClass.class /tmp/decompile-input/
   ```

3. **Choose the output directory**: Use a sensible location. Good defaults:
   - A `decompiled/` directory next to the input
   - Or a path the user specifies

4. **Determine the regex filter**: If the user wants all classes decompiled, use `".*"`. If they only want specific packages or classes, construct the appropriate regex (e.g., `"com\\.example\\..*"` for a specific package).

5. **Run the decompiler**:
   ```bash
   {SKILL_DIR}/scripts/run-decompiler.sh fernflower <inputDir> <outputDir> ".*"
   ```

6. **Report results**: After decompilation completes, tell the user where the output files are saved. List the generated `.java` files so they know what was produced.

## Important Notes

- The tool processes directories recursively — all `.class` and `.jar` files within subdirectories will be found and decompiled.
- Non-class files in the input directory are copied as-is to the output, preserving the directory structure.
- The tool uses a caching system (`cache.json` in the output directory) so re-running on the same input skips already-processed files.
- If decompilation fails with one engine, consider retrying with a different mode.
- Failed files are logged to `decompile_failed_list.txt` in the output directory.
- Build and packaging details belong in [`references/build.md`](references/build.md) and should only be loaded when maintaining the tool itself.

## Example

User: "Decompile the JAR at ~/libs/some-library.jar"

```bash
mkdir -p /tmp/decompile-input
cp ~/libs/some-library.jar /tmp/decompile-input/
{SKILL_DIR}/scripts/run-decompiler.sh fernflower /tmp/decompile-input ./decompiled ".*"
```

Then list the output:
```bash
find ./decompiled -name "*.java" | head -20
```
