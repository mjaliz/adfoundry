# AdFoundry

AdFoundry is an early-stage prototype for an agentic campaign builder. The goal is to turn a landing page URL and a campaign brief into brand-aware campaign assets: extracted brand context, campaign strategy, creative direction, copy, generated visuals, responsive HTML, and visual QA feedback.

The project is currently a minimal Python 3.12 codebase with `langgraph` and `playwright` dependencies. The intended product direction is an agentic workflow where specialized agents debate, make decisions, build campaign output, inspect the rendered result, and repair issues.

## Python Command Rule

Every Python command in this project must be run through the local virtual environment executable:

```bash
.venv/bin/python3
```

Do not run project Python commands with plain `python` or `python3`.

Examples:

```bash
.venv/bin/python3 main.py
.venv/bin/python3 -m playwright install
.venv/bin/python3 -m pytest
```

## Setup

Prerequisites:

- Python 3.12
- `uv`

Install dependencies:

```bash
uv sync
```

Install Playwright browsers:

```bash
.venv/bin/python3 -m playwright install
```

Create local configuration:

```bash
cp .env.example .env
```

Supported `.env` keys:

- `OPENAI_API_KEY`: enables live OpenAI agent reasoning.
- `OPENAI_BASE_URL`: optional OpenAI-compatible API base URL.
- `OPENAI_MODEL`: model used by the OpenAI Responses API adapter.
- `OPENAI_TIMEOUT_SECONDS`: OpenAI request timeout.
- `ADFOUNDRY_RUN_MODE`: `hybrid`, `fixture`, or `live`.
- `ADFOUNDRY_OUTPUT_ROOT`: directory for generated campaign packages.
- `ADFOUNDRY_BROWSER_TIMEOUT_MS`: Playwright page load timeout.
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`: optional path to a manually downloaded Chromium executable.

If you manually downloaded Chromium, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` in `.env` and skip `.venv/bin/python3 -m playwright install`:

```env
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/absolute/path/to/chromium
```

On macOS, the executable is usually inside the app bundle, for example:

```env
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/Applications/Chromium.app/Contents/MacOS/Chromium
```

`~` is supported and expands to your home directory:

```env
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=~/home
```

The value must point to the actual executable file, not only the folder or downloaded archive.

Run the current entrypoint:

```bash
.venv/bin/python3 main.py
```

Run the CEO demo dashboard:

```bash
.venv/bin/python3 -m streamlit run adfoundry/dashboard.py
```

Run tests:

```bash
.venv/bin/python3 -m pytest
```

## Product Vision

AdFoundry should behave like an autonomous creative production team:

- Browser Research Agent: opens the target URL, captures screenshots, extracts page text, images, logo candidates, and CSS colors.
- Brand Analyst Agent: interprets brand personality, product category, tone of voice, and visual style.
- Brand Guardian Agent: checks whether ideas stay consistent with the source brand.
- Campaign Strategist Agent: proposes campaign angles and selects the best strategy for the theme and goal.
- Creative Director Agent: defines visual concepts, image direction, composition, and mood.
- Copywriter Agent: writes headlines, subheadlines, CTAs, subject lines, and preheaders.
- UI Expert Agent: generates responsive HTML/CSS for the campaign.
- Visual QA Agent: reviews browser screenshots, evaluates quality, and sends repair instructions back to the UI Expert Agent.

## Intended Workflow

```text
User URL + campaign brief
        |
        v
Browser research and screenshot capture
        |
        v
Brand kit extraction
        |
        v
Agent strategy debate
        |
        v
Creative direction and copy generation
        |
        v
HTML/CSS generation by UI Expert Agent
        |
        v
Browser render with Playwright
        |
        v
Screenshot-based visual QA
        |
        v
Repair loop if needed
        |
        v
Final campaign package
```

## Decision-Making Layer

The important part of this project is not only automation. The agents should make and explain decisions.

Examples of decisions the system should expose:

- Which brand tone was selected and why.
- Which campaign angle was selected and which alternatives were rejected.
- Which visual concept best balances brand fit, creativity, and conversion.
- Which headline and CTA scored highest.
- Whether the rendered campaign passes visual quality, readability, CTA visibility, brand consistency, and mobile layout checks.

This decision trail should be visible in the demo through an agent activity panel or decision board.

## Documentation Requirements

Before implementing or changing LangGraph behavior, check the official LangChain documentation:

- https://docs.langchain.com/

Before implementing or changing Playwright behavior, check the official Playwright documentation:

- https://playwright.dev/python/docs/intro

This is especially important for browser automation, screenshots, page evaluation, async APIs, and any LangGraph workflow or multi-agent orchestration APIs.

## Current Status

The repository currently contains:

- `adfoundry/`: campaign workflow, browser helpers, fixtures, schemas, QA, and dashboard.
- `main.py`: minimal entrypoint.
- `pyproject.toml`: project metadata and dependencies.
- `uv.lock`: locked dependency versions.
- `chats.md`: product exploration notes for the agentic campaign builder concept.

Generated campaign runs are written to `outputs/<run_id>/` and ignored by git.

## Near-Term MVP

The first useful version should support:

1. Accept a landing page URL, campaign type, campaign goal, and theme.
2. Use Playwright to capture desktop and mobile screenshots.
3. Extract visible text, images, logo candidates, and color signals.
4. Build a structured brand kit.
5. Generate three campaign strategy options.
6. Let agents critique and select a final direction.
7. Generate copy and responsive HTML/CSS.
8. Render the HTML with Playwright.
9. Run screenshot-based visual QA.
10. Repair the campaign up to a fixed number of attempts.

The demo should emphasize this loop:

```text
Generate -> Inspect -> Critique -> Repair -> Approve
```
