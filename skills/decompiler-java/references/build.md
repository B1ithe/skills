## Build

```bash
mvn install:install-file -Dfile=engines/fernflower.jar -DgroupId=fernflower -DartifactId=fernflower -Dversion=2025-01-02 -Dpackaging=jar
mvn package
```

## Local Validation

Runtime requirement: Java 21 or newer.

```bash
java -jar target/JavaDecompiler-0.0.1.jar -h
Usage: Decompiler [-hV] [-m=<mode>] <inputDir> <outputDirBase> <classNameRegex>
      <inputDir>         The input directory
      <outputDirBase>    The output directory
      <classNameRegex>   classNameRegex
  -h, --help             Show this help message and exit.
  -m, --mode=<mode>      Decompiler mode[fernflower,cfr]
  -V, --version          Print version information and exit.

```
## Example

```bash
java -jar JavaDecompiler-0.0.1.jar -m=fernflower /path/to/input /path/to/output "cc.blithe.*"
```
*** Add File: /Users/blithe/Projects/SKILLS/.claude/commands/decompile-java.md
Decompile Java `.class` files or `.jar` archives with the repository-bundled decompiler.

Arguments: `$ARGUMENTS`

Workflow:
1. Read `skills/decompiler-java/SKILL.md` for the skill-specific workflow.
2. If the user gave a single `.class` or `.jar` file, stage it into a temporary input directory before running the tool.
3. Run `skills/decompiler-java/scripts/run-decompiler.sh <mode> <inputDir> <outputDir> <classNameRegex>`.
4. Default to `fernflower` unless the user requested another engine or a retry is needed.
5. Report the output directory, generated `.java` files, and any decompilation failures.
