# Contributing to Wawekit

Thank you for your interest in improving Wawekit! This guide explains how to set
up your environment and the standards we hold code to.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Project layout

Wawekit uses a strict layered architecture. **Dependencies must point downward
only:**

```
gui  ->  services  ->  models  ->  core
```

- Never import `gui` from `models` or `services`.
- Keep RDKit/science code out of `gui`.

## Coding standards

- Python 3.12+, **type hints everywhere**, **docstrings** on public objects.
- Format with `black`, lint with `ruff` (config in `pyproject.toml`).
- Use `logging`, never `print`, for diagnostics.
- No `TODO` placeholders in merged code — a feature ships complete.
- Handle exceptions explicitly; never let config/IO errors crash startup.

Before opening a pull request:

```bash
ruff check .
black --check .
pytest
```

## Commit & PR guidelines

- One logical change per pull request.
- Reference the module/issue it relates to.
- Add or update tests for behavior changes.
- Update the relevant `learning/` notes if you change how a module works.

## Reporting bugs

Open an issue including your OS, Python version, and the contents of the log
file (its path is printed at startup and shown under Help).

## Code of Conduct

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
