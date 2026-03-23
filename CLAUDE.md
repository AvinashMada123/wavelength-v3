# Wavelength v3 — Project Rules

## Repo Navigation
- Read REPO_STRUCTURE.md before exploring the codebase
- After creating, moving, or deleting files, update REPO_STRUCTURE.md to reflect the change

## Deployment
- Read docs/DEPLOYMENT.md before any deploy-related work
- All deploys must be atomic — never run partial deploy steps
- See docs/DEPLOYMENT.md for exact commands, critical rules, and incident-learned gotchas

## Testing — Non-Negotiable
- Every plan and spec MUST include unit tests and integration tests
- No PR or feature is complete without test coverage
- Frontend: TDD — write tests FIRST, then implementation (see frontend/CLAUDE.md)
- Backend: Tests written alongside implementation (see app/CLAUDE.md)

## Git Conventions
- Commit format: conventional commits — feat:, fix:, refactor:, perf:, test:, docs:, chore:
- Subject line: imperative mood, under 72 chars ("add X" not "added X")
- If the message needs "and", split into two commits
- One logical change per commit, target 50-200 lines changed
- Branch naming: type/short-description (e.g., feat/retry-scheduler, fix/echo-gate)
- Lowercase, hyphens only, no ticket numbers unless requested

## PR Standards
- Under 400 lines of changes per PR
- One concern per PR — don't bundle unrelated changes
- PR description must include: what changed, why, how to test
- All tests must pass before requesting review

## Comments
- Explain WHY, never WHAT — the code shows what
- No commented-out code — git has history
- No journal comments (// added on March 23)
- If you need a comment, first try to refactor so it's unnecessary
- Exceptions: complex algorithms, non-obvious business logic, workarounds with linked issues

## Code Quality
- Follow existing patterns in the codebase before inventing new ones
- No magic numbers — use named constants
- Functions should do one thing
- Prefer explicit over implicit
- No premature abstractions — Rule of Three before extracting
- Keep files focused — if a file exceeds 300 lines, consider splitting