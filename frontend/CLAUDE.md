# Frontend Rules (Next.js / TypeScript)

## Test-Driven Development (TDD) — Mandatory
- Write failing unit tests FIRST, then write code to make them pass
- Flow: Red (failing test) → Green (make it pass) → Refactor (clean up)
- No component or hook ships without tests
- Test file goes next to source: ComponentName.test.tsx alongside ComponentName.tsx

## Testing Standards
- Unit tests: Vitest + React Testing Library
- Test behavior, not implementation — test what the user sees and does
- No testing internal state or implementation details
- Mock external dependencies (API calls, contexts), not internal modules
- Integration tests: test component interactions and data flow
- Minimum expectations per component:
  - Renders without crashing
  - Key user interactions work
  - Edge cases: loading, error, empty states

## TypeScript
- Strict mode is ON — never bypass with @ts-ignore or `any`
- Define explicit types for props, API responses, and state
- Use discriminated unions over optional fields where possible

## Component Patterns
- Prefer small, focused components — if a file exceeds 200 lines, split it
- Keep business logic in hooks, keep components for rendering
- Colocate related files: component, test, types in same directory