# UK Bank Holidays MCP server

A small MCP server that lets AI assistants (Claude Code, Claude Desktop) look up UK bank holidays and count working days, using the official GOV.UK data: https://www.gov.uk/bank-holidays.json

## Why this project

A learning and portfolio project. Keep it small, readable and well tested: Wyatt must be able to explain every line. Prefer clear code over clever code, and explain each change briefly in plain English in chat, not in code comments (Rule 6 in `~/wyatt/CLAUDE.md`).

## Stack

- Python 3.14 (asdf; pinned in `.tool-versions` as `python 3.14.8`; the global asdf default stays 3.11 for work)
- Official MCP Python SDK 2.x: `mcp[cli]`, using `MCPServer` from `mcp.server.mcpserver` (2.x renamed 1.x's `FastMCP`; most tutorials still show the old name)
- `httpx2` for the one HTTP call (the `httpx` fork mcp 2.x uses; same API)
- `tzdata`, so `zoneinfo` can find `Europe/London` on Windows
- `pytest` for tests
- Virtual environment in `.venv`

## Data source

The GOV.UK JSON has three divisions: `england-and-wales`, `scotland`, `northern-ireland`. Each has `events`, and each event has `title`, `date` (YYYY-MM-DD), `notes` and `bunting`.

## Structure

```
pyproject.toml
src/uk_bank_holidays_mcp/
    __init__.py
    holidays.py   # pure logic: no network, no MCP, easy to test
    data.py       # fetch the GOV.UK JSON with httpx2, cached in memory for 24 hours
    server.py     # MCPServer: thin tool wrappers around holidays.py
tests/
    fixtures/bank-holidays.json   # small saved sample, so tests never use the network
    test_holidays.py
    test_server.py                # smoke test: start the server over stdio, list and call the tools
.claude/agents/
    mcp-tool-reviewer.md
README.md
```

## Tools (first version)

| Tool | Input | Output |
|---|---|---|
| `list_bank_holidays` | `division`, optional `year` (default: the current UK year) | list of `{date, title, notes}` |
| `next_bank_holiday` | `division`, optional `from_date` (default: today's UK date; the date itself counts) | `{date, title, notes, days_away}` |
| `is_bank_holiday` | `date`, `division` | `{date, is_bank_holiday, title, notes}` |
| `count_working_days` | `start`, `end`, `division` | weekdays between the two dates, both included, that are not bank holidays |

`division` is required in every tool. `notes` is GOV.UK's field, unchanged (e.g. `'Substitute day'`). The design decisions and the reasons for them are in `CONTEXT.md`.

Rules:
- Validate inputs. An unknown division gives a clear error listing the valid ones; a bad date or `start` after `end` gives a clear error.
- A date, year or range outside the covered years (years that have data in the GOV.UK file) is an error, never "not a bank holiday". So is a `next_bank_holiday` with no next holiday in the data. The error says which years are covered.
- Errors are raised as `ToolError`, so `MCPServer` sends them as tool errors (`isError`). Not `MCPError`: in 2.x that becomes a protocol-level failure.
- Tool descriptions must say what the tool does and what each argument means, because AI agents read them. Put them in `@mcp.tool(description=...)` and `Annotated[..., Field(description=...)]`, not in docstrings.
- All tools are read-only.
- Cache the GOV.UK response in memory for 24 hours; don't call GOV.UK on every tool call. If a refresh fails, keep using the old data; with no data at all, return an error. GOV.UK calls time out after 5 seconds, and after a failure, wait 1 hour before retrying.
- Tests must never use the network.

## Subagent

`.claude/agents/mcp-tool-reviewer.md`: a read-only reviewer (tools: Read, Grep, Glob) that checks every MCP tool for a clear name and description, typed and validated inputs, helpful error messages, read-only behaviour, and test coverage. Use it after adding or changing a tool.

## Skill

`grill-me` (lives in `~/wyatt/.claude/skills/grill-me/`, shared by personal projects; not part of this repo): asks hard questions one at a time to find gaps in a design before any code is written, and records decisions in `CONTEXT.md`. Use it before building a new tool or making a design change.

## Commands

- Set up: `$(asdf which python) -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`. Use `asdf which python`, not plain `python`: the VS Code terminal may already have a work virtualenv active, and its `python` would win. After a Python version change, `rm -rf .venv` and run this again.
- Test: `pytest`
- Run the server: `python -m uk_bank_holidays_mcp.server`
- Try it in Claude Code: `claude mcp add uk-bank-holidays -- /full/path/to/.venv/bin/python -m uk_bank_holidays_mcp.server`

## Build order

1. `pyproject.toml`, `.tool-versions`, `.gitignore`, venv
2. `holidays.py` with tests and the fixture
3. `data.py` with the 24-hour cache
4. `server.py` with the smoke test
5. The subagent; run it on `server.py` and fix what it finds
6. `README.md`: what it does, setup, the tools, and how to connect it to Claude Code

## Git

This is a personal project. Never use the work identity or work GitHub account.

- Commits must be authored as `Wyatt Hui <12708359+WyattHui@users.noreply.github.com>` (the GitHub noreply address, so the public repo doesn't show a real email; GitHub still links each commit to the `WyattHui` profile). This is set in this repo's own `.git/config`; the rest of `~/wyatt/` uses `~/.gitconfig-personal`. Check with `git config user.email` before committing; if it shows anything else, stop and tell Wyatt.
- Remote: `git@github-personal:WyattHui/uk-bank-holidays-mcp.git`. Never use a `git@github.com:` URL; that uses the work SSH key.
- Don't use `gh` to create the repo or PRs: it is logged in as the work account, not `WyattHui`. Wyatt creates the repo on github.com as `WyattHui`.

## Working agreement

- Small steps; run `pytest` after each one.
- Don't commit or push unless Wyatt asks. He reviews the diff first.
