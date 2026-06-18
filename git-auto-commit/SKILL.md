---
name: git-auto-commit
description: Analyze staged and unstaged Git changes, infer the repository's commit style from recent history, draft a detailed commit message, and create the commit safely. Use this skill whenever the user asks to commit code, generate a commit message, auto-stage and commit changes, or summarize local modifications into a polished Git commit, including requests such as "帮我提交代码", "生成 commit message", or "自动 git commit".
---

# Git Auto Commit

Create high-quality Git commits by combining local diff analysis, repository-specific message style, and cautious staging.

## Quick Start

1. Confirm the repository state with `git rev-parse --show-toplevel` and `git status --short`.
2. Run `{SKILL_DIR}/scripts/collect-git-context.py` from the target repository.
3. Review `git diff --cached` and `git diff` when the summary is not enough.
4. Stage only the cohesive working set, then write a detailed multi-line commit message.
5. Commit non-interactively and show the resulting summary with `git show --stat --summary -1`.

## Workflow

### 1. Inspect the change set

Start with the bundled context collector:

```bash
{SKILL_DIR}/scripts/collect-git-context.py
```

If the user gave a repository path, pass it explicitly:

```bash
{SKILL_DIR}/scripts/collect-git-context.py /path/to/repo
```

Supplement with:

- `git diff --cached`
- `git diff`
- `git log --oneline -10`

Use the collector output plus the raw diff to decide whether the changes belong in one commit or should be split.

### 2. Learn the repository's style

Mirror the recent commit history instead of forcing a universal format.

- If recent subjects mostly use conventional commits, keep that convention.
- Reuse an existing scope only when the changed files clearly cluster around one area.
- Default to a detailed multi-line message unless the change is truly tiny.

Load [references/commit-message-guidelines.md](references/commit-message-guidelines.md) only when you need extra examples or formatting heuristics.

### 3. Stage deliberately

Prefer explicit staging over `git add -A` when the user mentioned only part of the work.

- Stage only the files that match the requested change.
- Pause if the working tree mixes unrelated work that should become separate commits.
- Do not auto-stage clearly sensitive files such as `.env`, private keys, or credential exports unless the user explicitly wants them committed.
- Treat generated directories such as `dist/`, `build/`, `coverage/`, or minified bundles as review-required rather than automatic.

### 4. Write the commit message

Default message shape:

```text
<subject line>

- What changed
- Why it changed or what problem it solves

Tests: <command run, or "not run">
```

Rules:

- Keep the subject imperative and under 72 characters.
- Make the subject specific; avoid `update files`, `misc fixes`, or `wip`.
- Mention user-visible impact, behavior changes, or important refactors in the body.
- Include a `Tests:` line whenever validation was run or intentionally skipped.
- If the repo rarely uses bodies and the change is trivial, a single-line commit is acceptable, but the default for this skill is a detailed message.

Use `git commit --file <tmpfile>` for multi-line messages instead of stacking many `-m` flags.

### 5. Finish and report

After committing:

- Show `git status --short`
- Show `git log -1 --stat --decorate`
- Tell the user the commit hash, subject, and any remaining unstaged changes

## Ask Before Proceeding

Stop and confirm with the user when:

- the diff contains unrelated changes that should likely be split
- merge conflicts, rebases, or cherry-picks are in progress
- there are no changes to commit
- flagged sensitive files appear in the intended commit
- the user asked for one commit but the repo state suggests a narrower staging set

## Resources

### scripts/

`collect-git-context.py` prints a concise summary of staged, unstaged, and untracked changes; recent commit subjects; and review-required paths.

### references/

`commit-message-guidelines.md` contains lightweight heuristics and examples for detailed commit messages.
