# Repository Guidelines

## Project Structure & Module Organization

This is a small Python 3.12 project for the AdFoundry agentic campaign builder prototype.

- `adfoundry/`: campaign workflow, schemas, fixtures, browser helpers, QA logic, and Streamlit dashboard.
- `main.py`: fixture-mode command-line entrypoint.
- `pyproject.toml`: project metadata and runtime dependencies.
- `uv.lock`: locked dependency versions managed by `uv`.
- `README.md`: project overview, setup notes, and product direction.
- `chats.md`: product discovery notes and agent workflow ideas.

Tests are not present yet. When added, place them under `tests/` and mirror the source layout, for example `tests/test_main.py`. If the project grows, move application code into an `adfoundry/` package instead of expanding root-level scripts.

## Build, Test, and Development Commands

Install dependencies:

```bash
uv sync
```

Create local configuration:

```bash
cp .env.example .env
```

Configuration is loaded with `pydantic-settings` from `.env`. Use `OPENAI_BASE_URL` for an optional OpenAI-compatible base URL, `OPENAI_MODEL` for the live model, and `ADFOUNDRY_RUN_MODE` for the default runtime mode. If Chromium was downloaded manually, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to the browser executable path.

Run the app:

```bash
.venv/bin/python3 main.py
```

Run the local dashboard:

```bash
.venv/bin/python3 -m streamlit run adfoundry/dashboard.py
```

Install Playwright browsers:

```bash
.venv/bin/python3 -m playwright install
```

Run tests once tests exist:

```bash
.venv/bin/python3 -m pytest
```

Important: every Python command must use `.venv/bin/python3`. Do not use plain `python` or `python3` for project commands.

## Coding Style & Naming Conventions

Use standard Python style:

- 4-space indentation.
- `snake_case` for functions, variables, and module names.
- `PascalCase` for classes.
- Clear, typed function boundaries where practical.
- Short comments only when they clarify non-obvious agent workflow or browser automation logic.

No formatter or linter is configured yet. If adding one, document the command here and keep configuration in `pyproject.toml`.

## Testing Guidelines

Use `pytest` for tests. Name test files `test_*.py` and test functions `test_*`. Focus coverage on agent decision logic, structured outputs, Playwright extraction behavior, and HTML visual QA repair loops. Browser tests should use deterministic fixtures where possible rather than depending on live third-party pages.

Generated campaign artifacts are written to `outputs/<run_id>/` and should stay out of version control.

## Commit & Pull Request Guidelines

This repository has no commit history yet, so there is no established commit convention. Use concise, imperative commit messages such as:

```text
Add brand kit extraction scaffold
Document Playwright setup
```

Pull requests should include:

- A short summary of the change.
- Any new commands or setup steps.
- Test results, or a note explaining why tests were not run.
- Screenshots or rendered HTML previews for UI or Playwright output changes.

## Agent-Specific Instructions

Before changing LangGraph behavior, consult the official LangChain documentation: https://docs.langchain.com/

Before changing Playwright behavior, consult the official Playwright documentation: https://playwright.dev/python/docs/intro

Keep agent outputs structured and reviewable. Prefer explicit decision records, scorecards, and repair instructions over free-form agent chatter.
