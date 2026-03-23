# Backend Rules (FastAPI / Python)

## Testing — Alongside Development
- Write tests alongside implementation, not after
- Every new endpoint, service, or utility must have corresponding tests
- Test file location: tests/ directory, mirroring source structure (test_<module>.py)

## Testing Standards
- Framework: pytest with pytest-asyncio for async code
- Test real behavior — use test database where possible, minimize mocks
- Mock only external services (Plivo, Deepgram, Gemini API calls)
- Every endpoint test should cover: success case, validation errors, auth failures
- Test edge cases: empty inputs, missing fields, concurrent access

## Python Standards
- Type hints on all function signatures — parameters and return types
- Use Pydantic models for request/response validation
- Async by default — use async def for I/O-bound operations
- No bare except: — always catch specific exceptions
- Use pathlib over os.path

## FastAPI Patterns
- Dependency injection for shared resources (db sessions, auth)
- Use status codes explicitly (status.HTTP_201_CREATED, not 201)
- Keep route handlers thin — delegate to service layer
- Validate at the boundary (Pydantic models), trust internal code

## Pipeline Code (Pipecat)
- Processors should do one thing — compose pipelines, don't build mega-processors
- Always handle pipeline cleanup/shutdown gracefully
- Log processor state transitions for debugging
