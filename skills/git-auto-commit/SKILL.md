---
name: git-auto-commit
description: Analyze staged and unstaged Git changes, infer the repository's commit style from recent history, draft a detailed commit message, and create the commit safely. Use this skill whenever the user asks to commit code, generate a commit message, auto-stage and commit changes, or summarize local modifications into a polished Git commit, including requests such as "帮我提交代码", "生成 commit message", or "自动 git commit".
---

# Git Auto Commit

Create high-quality Git commits by combining local diff analysis, repository-specific message style, and cautious staging.

## Choose the Requested Outcome

- Message or summary only: inspect the relevant changes and return a draft. Do not stage or commit, and do not ask whether to commit merely because this skill supports it.
- Commit requested: inspect, stage the authorized change set, commit, and verify the result. Reuse an explicit request or prior approval for the same scope; apply the boundaries below if new ambiguity or sensitive content appears.
- No changes in the requested scope: report that fact and any unrelated changes. Do not ask for confirmation or create an empty commit.

## Quick Start

1. Inspect the repository state with `git rev-parse --show-toplevel` and `git status --short`.
2. Run `{SKILL_DIR}/scripts/collect-git-context.py` from the target repository.
3. Review `git diff --cached` and `git diff` when the summary is not enough.
4. Write the message; stage the cohesive working set only in the commit branch.
5. In the commit branch, commit non-interactively and show the resulting summary with `git show --stat --summary -1`. In the draft branch, return the message.

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

### 3. Select the change set and stage only for a commit

Prefer explicit staging over `git add -A` when the user mentioned only part of the work.

- Select only the files or hunks that match the requested change. If unrelated work is clearly separable, leave it untouched and proceed with the authorized set. Ask only when ownership or safe separation remains unclear, or when the proposed split changes the user's requested scope or commit count.
- Preserve unrelated staged and unstaged work. Inspect the actual commit contents before committing; do not include unrelated staged changes or reset the user's index to simplify selection. If the authorized set cannot be isolated safely, prepare the message and explain the specific conflict before asking.
- Collector flags are path-based review hints, not proof of sensitive content. Inspect the relevant diff without exposing secrets. A verified placeholder-only `.env.example` or ordinary source file whose name contains `token` may be included in the authorized set.
- Actual credentials, private keys, credential exports, or content whose sensitivity remains unresolved require explicit user approval covering those files before inclusion. Do not treat a generic request to commit as that approval.
- Review generated directories such as `dist/`, `build/`, `coverage/`, and minified bundles yourself. Include them only when they belong to the requested change and repository conventions require them to be tracked; ask if that cannot be established. A generated-file flag alone does not require user review.

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

For a draft, return the proposed message and any material uncertainty about its scope. For a commit, verify it was created and inspect the result:

- Show `git status --short`
- Show `git log -1 --stat --decorate`
- Tell the user the commit hash, subject, and any remaining staged, unstaged, or untracked work

If committing fails, inspect the error and continue with authorized, scoped recovery. Report an unresolved blocker and the prepared message rather than claiming the commit succeeded.

## Clarification and Approval Boundaries

Prepare the relevant diff review and message before asking. Pause only the affected staging or commit operation when:

- Change ownership, safe separation, or the requested commit scope/count remains unresolved after inspection.
- A merge, rebase, or cherry-pick is in progress and the user has not authorized the specific resolution or continuation. Read-only inspection and message drafting may continue; do not abort or continue the operation just to make a commit possible.
- Actual or unresolved sensitive content would enter the commit without the specific approval described above.

An existing approval remains valid for the same files, operation, and effects. New sensitive content or a material scope change requires a new decision; separable unrelated changes and an empty change set do not.

## Resources

### scripts/

`collect-git-context.py` prints a concise summary of staged, unstaged, and untracked changes; recent commit subjects; and review-required paths.

### references/

`commit-message-guidelines.md` contains lightweight heuristics and examples for detailed commit messages.
