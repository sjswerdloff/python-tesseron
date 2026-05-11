# Insights — python-tesseron test implementation

**Author:** vivian-1a61bc9a
**Date:** 2026-05-11
**Branch:** vivian/test-implementation

## Key observations from implementing the V-model test suite

### Pydantic field naming and mypy

When a Pydantic model uses `alias=` for a field (e.g. `schema` on the wire, `json_schema` in Python to avoid shadowing `BaseModel.schema`), mypy does not know about the Python-side field name at the call site — it only sees the alias. This means even with `populate_by_name=True`, mypy will reject `MyModel(python_field_name=...)` as a `call-arg` error.

**Fix:** Use `Model.model_validate({...})` with the alias-keyed dict for mypy-clean construction in tests. This is also more explicit about deserialisation intent.

### Websockets subprotocol typing

`websockets>=13` requires `Subprotocol` typed strings (not plain `str`) in the `subprotocols=` list. Passing a raw string works at runtime but mypy flags it as `list-item` error. Import `from websockets import Subprotocol` and wrap: `[Subprotocol(SUBPROTOCOL)]`.

### ruff D413 — blank line after last section

Google-style docstrings require a blank line after the final section (e.g., `Attributes`, `Args`). Running `ruff check --fix` auto-corrects all D413 violations. The pyproject.toml already ignores D203/D213 (one-blank-line vs two-blank-line conflicts), but D413 is not in the ignore list and should be fixed rather than suppressed.

### ruff D301 — backslash in docstring and traceability checker conflict

Docstrings containing backslash sequences (e.g., `\n` as a wire format description) should use `r"""..."""` raw strings to satisfy D301. However, the traceability checker regex `\"\"\"(.*?)\"\"\"` only matches plain triple-quote docstrings — it does not match `r"""`.

**Resolution:** Reword the docstring to avoid the backslash entirely rather than using `r"""`. This satisfies both D301 (no backslash violation) and the traceability checker (plain `"""` is matched). Writing `"appends a newline"` instead of `"adds '\\n'"` is more readable anyway.

### Test collection requires `pythonpath = ["."]` for cross-module imports

When test files import from `tests.conftest` (needed to expose `MockGateway` type hint and helper functions), pytest cannot find the `tests` module without either:
1. Adding `pythonpath = ["."]` to `[tool.pytest.ini_options]` in pyproject.toml, OR
2. Adding `tests/__init__.py` to make it a package.

Both are needed: the `__init__.py` makes it a proper package for IDE and mypy, and `pythonpath` ensures the root is on `sys.path` so `import tests.conftest` resolves.

### xfail is the correct V-model pattern for pre-implementation tests

Using `@pytest.mark.xfail(reason="implementation pending: ...")` for all SDK-integration tests is exactly right. These tests:
- Collect without errors (`pytest --co` passes)
- Are documented as expected failures (`xfailed` in results)
- Will automatically become `xpass` failures (drawing attention) if the implementation is partially done but the test isn't un-marked
- Serve as runnable specification documents for the implementer

### 50 tests pass without any implementation

By writing careful structural tests (error codes, model fields, regex validation, state ordering, JSON-RPC envelope rules), 50 tests pass from stubs alone. This validates that the stub types and errors modules are correctly structured, and gives immediate CI feedback without requiring the full SDK.

### Traceability gap fixing: two categories of fix

When a requirement traceability checker reports unreferenced requirements, there are two categories of resolution:

1. **Add REQ reference to an existing test docstring.** If a test already exercises the requirement's behaviour, simply add the `REQ-xxx` identifier to the docstring. The checker scans docstrings for `REQ-NNN` tokens — no code changes needed.

2. **Create a new structural test.** If no test covers the requirement and a structural test is feasible (e.g., a model field has a fixed value mandated by the spec), add a small non-xfail test.

3. **Document excluded requirements in a comment block.** Process/meta/design constraints (clean-room workflow, meta-requirements, permissive MAY clauses) cannot be tested in code. Add a comment block at the top of the most relevant test file explaining why they are excluded. The checker does NOT count these as errors — only missing *spec test IDs* and *invalid REQ references* fail the checker. Unreferenced requirements are reported as informational in verbose mode but do not cause a FAIL.
