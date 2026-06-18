# Commit Message Guidelines

Load this file only when `SKILL.md` is not enough and you need extra heuristics or examples.

## Style Detection

- Scan the last 8-12 commit subjects before drafting a message.
- If at least 60% match `type(scope): subject`, stay with conventional commits.
- Reuse a scope only when the changed files clearly map to one module or surface area.

## Preferred Shape

```text
feat(scope): concise subject

- Explain the main code changes
- Mention behavior, workflow, or maintenance impact when useful

Tests: <command run, or "not run">
```

## Subject Heuristics

- Use imperative present tense.
- Keep it under 72 characters.
- Prefer specific verbs and nouns.
- Avoid vague subjects such as `update files`, `misc fixes`, `small changes`, or `wip`.

## Example Subjects

- `feat(skills): add git auto-commit workflow`
- `chore(claude): add repo-level commit command`
- `Refine commit message generation for staged diffs`

## Example Body Lines

- `- summarize staged and unstaged changes before drafting the message`
- `- flag .env and credential files for manual review before staging`
- `Tests: python3 /Users/blithe/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/git-auto-commit`

## Split Instead Of Forcing One Commit

- unrelated refactor plus feature work
- version bumps mixed with behavior changes
- generated assets mixed with source edits unless they must ship together
