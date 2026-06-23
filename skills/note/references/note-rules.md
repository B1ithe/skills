# Note Rules

These rules are the source of truth for the `note` skill.

## Vault Model

- The working root is the Obsidian vault root. It contains topic directories,
  optional `.obsidian/`, and optional `RAW/`.
- There is no required outer directory and no required `Root/` child.
- `.obsidian/` is editor configuration. The note skill does not read, format,
  health-check, rename, ingest, or modify files under `.obsidian/`.
- `RAW/` stores local source material. It may be absent.
- Existing RAW content is read-only except for confirmed cross-platform
  filename repairs.
- `RAW/Clippings/` is the standard location for web clippings.
- `RAW/AiSaves/` is the standard location for pages saved by agents.
- RAW assets live under `RAW/Clippings/assets/{slug}/` or
  `RAW/AiSaves/assets/{slug}/`.

## Frontmatter

Every maintained Markdown note starts with YAML frontmatter:

```yaml
---
title: microgpt
created: 2026-05-27
updated: 2026-06-09
tags:
  - llm
sources:
  - path: RAW/Clippings/microgpt.md
    sha256: 6e6c6fcb8e60e34d0054409432a16468f4842cc84078cffe660b4bc4f3f54c2c
    url: https://example.com/microgpt
---
```

Required fields:

- `title`: human-readable title.
- `created`: `YYYY-MM-DD`.
- `updated`: `YYYY-MM-DD`.
- `tags`: list of short topic tags.
- `sources`: list of raw source records, or `[]` for original notes.

Each source record has:

- `path`: required vault-relative path beginning with `RAW/`.
- `sha256`: required lowercase SHA-256 digest of the raw file at ingest time.
- `url`: optional original URL.

Frontmatter is the only source registry. Do not repeat source paths, URLs,
authors, attachment mappings, or original metadata in the note body.

## Content

- Write Chinese prose by default. Preserve original titles, proper nouns, and
  technical terms when useful.
- Write direct topic explanations, not article reviews or source commentary.
- Keep each note understandable on its own.
- Preserve reasoning, prerequisites, execution order, important intermediate
  steps, representative code, commands, outputs, failure conditions, expected
  results, caveats, and applicability limits.
- Remove repetition, conversational filler, and promotional language.
- Update an existing complete note when new evidence fits its topic. Create a
  new note only when merging would make an existing note incoherent or too
  broad.
- Use Obsidian `[[Internal Links]]` only for genuinely related maintained
  notes. Internal links do not replace essential explanation.

## Organization

- Store notes in topic directories, commonly Chinese topic names.
- Do not organize notes by page role such as concepts, questions, entities, or
  syntheses.
- Add nested topic directories only when they improve browsing.
- Every Markdown filename stem should be unique across the vault so short
  Obsidian links resolve unambiguously.

## Cross-Platform Filenames

All note-managed vault paths, including `RAW/`, should be legal on Linux and
Windows. `.obsidian/` is excluded from filename checks and repairs.

- Forbidden characters: `< > : " / \ | ? *`.
- Control characters are forbidden.
- Names must not end with a space or dot.
- Avoid Windows reserved names, case-insensitive:
  `CON`, `PRN`, `AUX`, `NUL`, `COM1` through `COM9`, `LPT1` through `LPT9`.
- New note filenames replace illegal characters with spaces, collapse repeated
  whitespace, trim spaces and dots, and use `untitled-note` if empty.
- Windows reserved names are repaired by appending `-note`.
- Same-directory conflicts are repaired with `-2`, `-3`, and so on.
- Case-insensitive conflicts require manual handling.
- Health reports unsafe names. Rename apply runs only after user confirmation.
- RAW path repairs may rename RAW files/directories and update maintained note
  `sources[].path`. RAW file contents are not edited by default.

## Assets

- Reader-facing files live beside the maintained note under
  `./assets/{noteFileName}/`.
- Use note-relative Markdown paths such as
  `./assets/microgpt/diagram.png`.
- This rule applies to images, PDFs, spreadsheets, archives, source samples,
  firmware, and other downloadable files.
- Keep original source attachments in `RAW/`. Copy only useful reader-facing
  assets into maintained note asset directories.

## URL Ingest

- Save agent-read pages to `RAW/AiSaves/{slug}.md`.
- Include original URL, access date, and title.
- Save reliable assets to `RAW/AiSaves/assets/{slug}/`.
- If asset downloads are unreliable, record original asset URLs in the saved
  Markdown and continue.
- Ingest the saved page through the normal RAW workflow.

## Format

- Formatting missing frontmatter requires scan, candidate display, explicit
  user confirmation, and apply.
- Missing frontmatter is a format candidate, not a fix blocker.
- Treat first line `---` as existing frontmatter. Do not repair existing
  invalid or unterminated frontmatter in the format workflow.
- Insert only `title`, `created`, `updated`, `tags`, and `sources`.
- `title` is the first Markdown H1 outside fenced code, otherwise filename
  stem.
- `created` and `updated` both use the apply date.
- Preserve the original body bytes after inserted frontmatter.

## Health

Health checks machine-verifiable note structure only:

- valid existing frontmatter and required field types.
- source path format, existence, and registered SHA-256 match.
- duplicate source registrations.
- broken internal links.
- duplicate Markdown filename stems.
- local attachment location and existence.
- cross-platform filename safety, including `RAW/`, excluding `.obsidian/`.

Missing frontmatter and missing required frontmatter fields are reported as
update/format candidates. They are not fix blockers by themselves:

- Missing frontmatter routes to the format workflow.
- Missing required fields in existing frontmatter route to the update workflow.
- Invalid, unterminated, or semantically inconsistent existing frontmatter
  remains a repair problem.

Health does not judge prose quality, topic fit, or knowledge organization.

## Fix Planning

- When health fails, the agent creates the fix plan. There is no generic fix
  script.
- User-facing fix plans and explanations use Chinese by default.
- First group health errors by repair type, then show a concise plan table.
- Exclude update/format candidates from the fix queue unless the user
  explicitly asks to handle them there.
- Ask which group to handle first before reading and editing many files.
- Apply only confirmed, scoped repairs.
- Use deterministic scripts only for narrow operations:
  - `note_rename.py` for unsafe filenames.
- Use batch confirmation only for deterministic low-semantic-risk operations.
- Use review confirmation for attachment relocation, Markdown note-link
  conversion, and existing frontmatter field repair.
- Use single confirmation for RAW moves, content deletion, topic changes,
  duplicate source ownership, and broken wikilinks without an obvious target.
- Do not modify `.obsidian/` as part of fix planning or repair.

## Commits

Create a Git commit after meaningful note writes unless the user explicitly
asks not to commit. Do not commit read-only health or inventory checks.

Run health before committing. If health fails, fix the issue before committing
or report why it cannot be fixed safely.

Stage only files related to the task. Do not commit real source material unless
the task intentionally saved or renamed that RAW material.

Commit message format:

```text
note(<scope>): <summary>

- <what changed>
- <why it changed or what source it came from>

Sources: <RAW path, URL, note path, or "none">
Tests: <command run, or "not run">
```

Recommended scopes: `ingest`, `topic`, `answer`, `format`, `health`, `repo`.
