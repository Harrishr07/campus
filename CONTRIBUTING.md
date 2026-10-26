# Contributing to OneBook Campus

## Branches

| Branch | Purpose |
|---|---|
| `main` | Released code: what a pilot or demo site runs. Changed only by a pull request from `develop` (or a hotfix). |
| `develop` | Integration branch. Every feature and fix pull request targets `develop`. |
| `feat/<topic>`, `fix/<topic>`, `chore/<topic>` | Short-lived work branches, cut from `develop`. |

Contributors working from a fork open their pull request against `OneBook-ERP/campus:develop`.

## Commits

Use conventional commit subjects, `type(scope): subject`, for example `fix(admissions): ...`. Allowed types: feat, fix,
docs, style, refactor, perf, test, build, ci, chore, revert. CI checks this on every pull request.

## Before you push

```bash
pip install pre-commit
pre-commit install          # runs ruff, prettier and eslint on each commit
pre-commit run --all-files  # the same checks CI runs
```

To hide the one-time formatting commit from `git blame`:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

## Tests

Tests run on a dedicated test site, never on a development or pilot site:

```bash
bench --site campus-test.localhost run-tests --app campus --module campus.tests.test_<area>
```

A new rule or permission comes with a test that exercises it as the role concerned. A patch that changes existing
records is idempotent and only touches rows campus itself wrote.

## Continuous integration

- **Linters** (every pull request): pre-commit, Frappe's Semgrep rules, commit subjects.
- **Server Tests**: a pull request installs every app on a fresh site, migrates, and runs a quick set of modules. A push to
  `develop` or `main`, and a nightly run on `develop`, run the full suite split over eight runners.
- **CodeRabbit** reviews each pull request against the rules in `.coderabbit.yaml`.

A pull request is merged when the checks pass and a maintainer has approved it.
