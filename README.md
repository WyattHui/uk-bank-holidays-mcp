# UK Bank Holidays MCP server

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants such as Claude Code look up UK bank holidays and count working days, using the official GOV.UK data at <https://www.gov.uk/bank-holidays.json>.

It is built to give an assistant **answers it can trust**: when the data cannot answer a question, the tool says so instead of guessing.

## What it does

Four read-only tools, each for one of the three UK regions GOV.UK publishes: `england-and-wales`, `scotland` and `northern-ireland`.

| Tool | Arguments | Returns |
|---|---|---|
| `list_bank_holidays` | `division`, optional `year` (default: this year) | each holiday's `date`, `title` and `notes` |
| `next_bank_holiday` | `division`, optional `from_date` (default: today) | the next holiday on or after that date, with `days_away` |
| `is_bank_holiday` | `date`, `division` | `is_bank_holiday`, plus `title` and `notes` if it is one |
| `count_working_days` | `start`, `end`, `division` | the number of weekdays that are not bank holidays, both dates included |

Dates are `YYYY-MM-DD`. For example, `is_bank_holiday` with `date: 2026-11-30` and `division: scotland` returns:

```json
{"date": "2026-11-30", "is_bank_holiday": true, "title": "St Andrew’s Day", "notes": ""}
```

### Behaviour worth knowing

- **No guessing outside the data.** GOV.UK publishes a limited range of years (2019 to 2028 in October 2026). A date in any other year returns an error saying which years are covered, never "not a bank holiday". So does a working-days range that is only partly covered.
- **The region is always required.** Bank holidays differ between regions: 30 November is St Andrew’s Day in Scotland only. Making `division` required stops an assistant silently answering for England.
- **Substitute days are marked.** When a holiday falls on a weekend, the day off moves to a weekday, keeps the original title and has `notes: "Substitute day"`. For example, Christmas Day 2027 is a Saturday, so 27 December 2027 is listed as "Christmas Day".
- **A misspelled argument is an error.** Sending `date` instead of `from_date`, or `years` instead of `year`, returns an error listing the names the tool takes, rather than quietly using the default.
- **"Today" is the UK date**, whatever the time zone of the computer running the server.
- **GOV.UK is normally called once a day.** The data is cached in memory for 24 hours. If a refresh fails, the server keeps using the data it has and tries again an hour later, every hour until it succeeds. If it has no data at all, the tool returns an error saying the data could not be got from GOV.UK.

## Setup

You need Python 3.14 or later.

```bash
git clone https://github.com/WyattHui/uk-bank-holidays-mcp.git
cd uk-bank-holidays-mcp
python3.14 -m venv .venv
.venv/bin/pip install -e .
```

If you use [asdf](https://asdf-vm.com), `.tool-versions` pins the Python version: run `$(asdf which python) -m venv .venv` instead of `python3.14 -m venv .venv`.

## Connect it to Claude Code

From the repository folder:

```bash
claude mcp add uk-bank-holidays -- "$PWD/.venv/bin/python" -m uk_bank_holidays_mcp.server
```

This adds it for the current folder only. Add `--scope user` after `add` to use it in every project. Then ask Claude things like:

- "Is 30 November 2026 a bank holiday in Scotland?"
- "How many working days are there in England in December 2026?"
- "When is the next bank holiday in Northern Ireland?"

Any other MCP client that runs local stdio servers works the same way: the command is `.venv/bin/python` and the arguments are `-m uk_bank_holidays_mcp.server`.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/flake8
```

- The tests never use the network: they run against a saved sample of the GOV.UK data in `tests/fixtures/`. `tests/test_server.py` starts the real server over stdio and calls each tool.
- `CONTEXT.md` records each design decision and the reason for it.
- `.claude/agents/mcp-tool-reviewer.md` is a Claude Code subagent that reviews the tools after a change.

## Licence

The code is under the MIT licence: see [LICENSE](LICENSE).

Bank holiday data comes from GOV.UK. Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
