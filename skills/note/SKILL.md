---
name: note
description: Maintain a local Markdown/Obsidian note vault. Use when Codex should update notes from RAW files or URLs, answer from maintained notes, save approved knowledge back into the vault, format notes missing frontmatter, run note health checks, plan agent-driven fixes for health blockers, inventory RAW sources, or repair cross-platform unsafe filenames.
---

# Note

Use this skill in a vault root. The current working directory should contain
topic directories directly, with optional `.obsidian/` and `RAW/` directories.
Do not assume an outer repository directory containing `Root/`.

Treat `.obsidian/` as editor configuration, not note content. Do not inspect,
format, health-check, rename, ingest, or otherwise modify files under
`.obsidian/`.

Scripts require PyYAML. If `import yaml` fails, install from this skill's
`requirements.txt`.

## Rules

Read `references/note-rules.md` before any write operation: ingest, save,
format, rename, or commit. For a read-only answer, search first and read the
rules only if you need to explain policy or prepare a write.

## Health

Run structural checks:

```sh
python <skill-dir>/scripts/note_health.py --root "$PWD"
```

Health may report update/format candidates that are not health blockers. Route
missing frontmatter to `Format`, and missing required frontmatter fields to
`Update`; do not treat them as fix work unless the existing frontmatter is
invalid or semantically inconsistent.

If health fails, create a fix plan before editing:

1. Group health errors by repair type.
2. Present a concise Chinese plan table.
3. Ask the user which group to handle first.
4. Read the relevant files for that group.
5. Propose exact edits or script commands.
6. Apply only confirmed, scoped fixes.
7. Run health again.

Use these confirmation levels:

- Batch confirmation: unsafe filenames via `note_rename.py`.
- Review confirmation: attachment relocation, Markdown note-link conversion,
  and semantically inconsistent existing frontmatter field repair.
- Single confirmation: RAW moves, content deletion, topic changes, duplicate
  source ownership, broken wikilinks without an obvious target.

Write the fix plan and user-facing explanations in Chinese.

If unsafe filenames are reported, create a repair plan:

```sh
python <skill-dir>/scripts/note_rename.py plan --root "$PWD" --json > /tmp/note-rename-plan.json
```

Show the plan, conflicts, and warnings to the user. Apply only after explicit
confirmation:

```sh
python <skill-dir>/scripts/note_rename.py apply --root "$PWD" --plan /tmp/note-rename-plan.json
python <skill-dir>/scripts/note_health.py --root "$PWD"
```

## Inventory

Inspect RAW ingest state:

```sh
python <skill-dir>/scripts/source_inventory.py --root "$PWD" --json
```

Process only `new` or `changed` items unless the user asks for a rebuild.
Resolve `duplicate` registrations before ingesting more sources.

## Update

1. Read `references/note-rules.md`.
2. Inventory RAW sources, or save a user-provided URL into `RAW/AiSaves/`.
3. Treat maintained notes with missing required frontmatter fields as update
   candidates, not fix candidates.
4. Search maintained notes before creating a new note.
5. Update an existing topic note when the source fits; otherwise create a
   complete note in the best topic directory.
6. Register each ingested source in frontmatter `sources`.
7. Copy only useful reader-facing assets to `./assets/{noteFileName}/`.
8. Run health.
9. Commit only related note changes when health passes.

## Answer

Search maintained notes under the vault, excluding `RAW/`. Read RAW only when
maintained notes are missing evidence, stale, or ambiguous. Clearly separate
source-grounded facts from synthesis.

Do not write after the first answer unless the user explicitly asks to save,
update, or沉淀 the result. Before saving, read `references/note-rules.md`; after
saving, run health and commit related note changes.

## Format

Scan for maintained Markdown notes that do not begin with frontmatter:

```sh
python <skill-dir>/scripts/note_format.py scan --root "$PWD" --json > /tmp/note-format-inventory.json
```

List candidates in path order with one-based numbers and proposed titles. Wait
for explicit confirmation. Apply selected paths:

```sh
python <skill-dir>/scripts/note_format.py apply --root "$PWD" --inventory /tmp/note-format-inventory.json --note <vault-relative-path>
```

If any selected note changed after scanning, scan again and request fresh
confirmation. Run health and commit only selected note changes when health
passes.
