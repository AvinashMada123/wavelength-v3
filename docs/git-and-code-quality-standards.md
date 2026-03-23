# Git Conventions & Code Quality Standards

> Compiled from: Google eng-practices, Conventional Commits spec, Chris Beams' git commit guide, Trunk Based Development, and practices at Linear, Vercel, Stripe, and Meta.

---

## 1. Git Commit Conventions

### Format: Conventional Commits (Industry Standard)

```
<type>(optional-scope): <description>

[optional body]

[optional footer(s)]
```

### Allowed Types

| Type | When to use |
|------|-------------|
| `feat` | New feature (maps to SemVer MINOR) |
| `fix` | Bug fix (maps to SemVer PATCH) |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `style` | Formatting, semicolons, whitespace (no logic change) |
| `build` | Build system or external dependencies |
| `ci` | CI configuration changes |
| `chore` | Maintenance tasks (deps, configs) |

### Rules

1. **Subject line**: Max 50 chars (soft), 72 chars (hard limit)
2. **Capitalize** the subject line: `feat: Add user export` not `feat: add user export`
3. **Imperative mood**: "Add feature" not "Added feature" or "Adds feature"
4. **No period** at end of subject line
5. **Blank line** between subject and body
6. **Body**: Wrap at 72 characters. Explain *what* and *why*, not *how*
7. **Breaking changes**: Use `!` after type or `BREAKING CHANGE:` footer
8. **Scope** is optional but useful: `feat(api):`, `fix(auth):`, `refactor(pipeline):`

### Examples

```
feat(leads): add CSV export with column selection

Users requested the ability to export leads as CSV with custom columns.
This adds a dropdown to select visible columns before export.

Closes #142
```

```
fix(auth): handle expired refresh tokens gracefully

Previously, expired refresh tokens caused a 500 error.
Now returns 401 with a clear message prompting re-login.
```

---

## 2. Branching Strategy

### Recommendation: Trunk-Based Development (with short-lived feature branches)

This is what Google, Meta, Stripe, Linear, and Vercel all converge on. GitFlow is considered legacy.

### Rules

1. **One long-lived branch**: `main` (the trunk)
2. **Feature branches** live max **1-3 days** (ideally < 1 day)
3. **No long-lived develop/staging branches** — use feature flags instead
4. **Release branches** (if needed) are cut from trunk just-in-time and deleted after release
5. **Merge strategy**: Squash-merge feature branches into main (clean linear history)
6. **Feature flags** for incomplete work that must merge to trunk
7. **Branch by abstraction** for large refactors spanning multiple PRs

### Why Not GitFlow?

- Merge conflicts compound with long-lived branches
- Delays integration and hides bugs
- Adds ceremony without value for most teams
- DORA research confirms trunk-based = higher delivery performance

---

## 3. Commit Size & Atomicity

### The Google Standard: "One Self-Contained Change"

1. Each commit addresses **exactly one thing** — one bug fix, one refactor, one feature slice
2. The codebase **compiles and passes tests** after every commit
3. Include **related test code** in the same commit as the production code
4. If a commit message needs "and" — split it into two commits
5. **Target**: 50-200 lines changed per commit (excluding tests/generated files)
6. Large features should be split into a **stack of small PRs**

### How to Split

- **Vertical slicing**: One end-to-end thin slice of functionality at a time
- **Layer by layer**: API types first, then backend logic, then UI
- **Refactor separately**: Extract refactors into their own commits/PRs before the feature

---

## 4. Branch Naming Conventions

### Format

```
<type>/<ticket-id>-<short-description>
```

### Rules

1. **Lowercase**, hyphens only (no underscores, no camelCase)
2. **Prefix with type**: `feat/`, `fix/`, `refactor/`, `chore/`, `hotfix/`
3. **Include ticket ID** if using a tracker: `feat/ENG-142-csv-export`
4. **Keep it short**: 3-5 words max in description
5. **No personal names**: `feat/csv-export` not `animesh/csv-thing`

### Examples

```
feat/WV-42-lead-csv-export
fix/WV-108-auth-token-expiry
refactor/pipeline-factory-cleanup
chore/upgrade-pipecat-0.0.105
hotfix/plivo-websocket-crash
```

---

## 5. PR Hygiene

### What Top Teams Require

#### PR Structure
1. **Title**: Conventional commit format — `feat(scope): short description`
2. **Description must include**:
   - **What** changed (summary, not line-by-line)
   - **Why** it changed (context, problem statement)
   - **How to test** (steps or automated test pointers)
   - **Screenshots/recordings** for UI changes
3. **Size**: Under 400 lines of meaningful diff (Google's recommendation)
4. **One concern per PR** — never mix refactors with features

#### Process
5. **Self-review first**: Read your own diff before requesting review
6. **CI must pass** before review is requested
7. **Link to issue/ticket** in the description
8. **Draft PRs** for early feedback on direction
9. **Respond to all comments** — resolve or explain why not
10. **Squash-merge** to keep main history clean

#### Review Checklist (Google's Standard)
- [ ] Design: Is this the right approach?
- [ ] Functionality: Does it work correctly?
- [ ] Complexity: Can it be simpler?
- [ ] Tests: Are they correct and sufficient?
- [ ] Naming: Are names clear and consistent?
- [ ] Comments: Are they useful (not redundant)?
- [ ] Style: Does it follow project conventions?

---

## 6. Code Comment Standards

### The "Necessary Comments Only" Philosophy

From Clean Code (Robert C. Martin), Google style guides, and modern engineering consensus:

#### DO Comment
1. **Why**, never **what** — explain intent, business rules, non-obvious decisions
2. **Warnings**: `// WARNING: Order matters — auth middleware must run before rate limiter`
3. **TODOs with tickets**: `// TODO(WV-200): Replace with batch API when available`
4. **Legal/license headers** (if required)
5. **Public API docs**: Function signatures that others will call
6. **Regex/complex algorithms**: Explain what a non-obvious pattern does
7. **Workarounds**: `// HACK: Plivo sends duplicate events; deduplicate by call_id + timestamp`

#### DO NOT Comment
1. **What the code does** — if you need to explain what, rename the variable/function instead
2. **Commented-out code** — delete it; git has history
3. **Journal comments** (`// Added by Animesh on 2026-03-15`) — git blame exists
4. **Closing brace comments** (`// end if`, `// end for`) — your function is too long
5. **Redundant docs**: `// Returns the user` on `def get_user()`
6. **Noise comments**: `// Default constructor`, `// Getters and setters`

#### Rule of Thumb
> "A comment is a failure to express yourself in code. If you need a comment, first try to refactor so the comment becomes unnecessary."

---

## 7. Code Quality Standards

### What Top Teams Enforce (Non-Negotiable)

#### Formatting & Linting (Automated, Zero Debate)
1. **Formatter**: Prettier (JS/TS), Black (Python), gofmt (Go) — run on save, enforce in CI
2. **Linter**: ESLint (JS/TS), Ruff (Python), clippy (Rust) — block merges on violations
3. **Import sorting**: Automated (isort for Python, ESLint plugin for JS)
4. **No linting exceptions without justification** in the disable comment

#### Type Safety
5. **TypeScript**: `strict: true` in tsconfig (no `any` without explicit justification)
6. **Python**: Type hints on all function signatures; mypy or pyright in CI
7. **No implicit any, no type assertions without comments**

#### Code Structure
8. **Single Responsibility**: One function does one thing
9. **DRY but not prematurely**: Duplicate twice before abstracting (Rule of Three)
10. **Max function length**: ~20-30 lines (if longer, extract)
11. **Max file length**: ~300-400 lines (if longer, split)
12. **Flat over nested**: Max 2-3 levels of indentation; early returns over nested ifs

#### Testing
13. **Unit tests for business logic** — not for glue code
14. **Test behavior, not implementation** — test public interfaces
15. **Descriptive test names**: `test_expired_token_returns_401` not `test_auth_3`
16. **No test interdependence** — each test must run in isolation

#### Pre-Commit Hooks (Enforce Locally)
17. **Lint + format** on staged files (husky + lint-staged for JS; pre-commit for Python)
18. **Type check** on commit
19. **Commit message format** validation (commitlint)

#### CI Pipeline (Enforce on PR)
20. **Lint, format check, type check** — must pass
21. **All tests pass** — no flaky test exceptions without tracking
22. **Build succeeds** — no broken builds on main, ever
23. **Security scan** (dependabot, snyk, or similar)
24. **Coverage gate** — don't decrease coverage (but don't worship 100%)

---

## Quick Reference: The Non-Negotiable Rules

| Category | Rule |
|----------|------|
| Commits | Conventional Commits format, imperative, < 72 chars |
| Branches | `type/ticket-description`, short-lived (< 3 days) |
| PRs | < 400 lines, one concern, description with what/why/how-to-test |
| Comments | Explain *why* not *what*, no commented-out code |
| Formatting | Automated (Prettier/Black), enforced in CI |
| Types | Strict mode, no escape hatches without justification |
| Tests | Test behavior not implementation, descriptive names |
| CI | Lint + types + tests + build must all pass before merge |