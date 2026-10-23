# CONTEXT

Shared language and decisions for the UK Bank Holidays MCP server. Built during `/grill-me` sessions.

## Glossary

- **Division**: one of the three GOV.UK regions: `england-and-wales`, `scotland`, `northern-ireland`. Each has its own list of bank holidays.
- **Covered year**: a year that has at least one bank holiday in the GOV.UK data for that division. Worked out from the data each time it is fetched, never hard-coded. On 2026-10-20 all three divisions cover 2019 to 2028.
- **Outside the data**: a date whose year is not a covered year. A date after the last listed holiday but inside a covered year (e.g. 2028-12-29) is *inside* the data.

## Decisions

### 1. A date outside the data is an error (2026-10-20)

`is_bank_holiday('2030-12-25')` returns an error, not "not a bank holiday". The error message says which years are covered. `is_bank_holiday('2028-12-29')` answers "No" as normal, because 2028 is a covered year.

**Why:** outside the data, the honest answer is "unknown". A "no" there is a confident wrong answer, and AI agents pass tool output straight on to the user. The rule is by year, not by the last listed holiday, because GOV.UK publishes whole years: a date after 26 Dec 2028 is still known not to be a holiday.

### 2. A range that is partly outside the data is an error (2026-10-20)

`count_working_days('2028-12-01', '2029-01-31')` returns an error for the whole request. It does not count the covered part.

**Why:** same reason as decision 1. A partial count looks like a full answer, and an agent would pass it on as one.

### 3. If GOV.UK fails, keep using the old data (2026-10-20)

When the 24-hour cache expires and the refresh fails for any reason (GOV.UK error, timeout, no network, a response that is not bank holiday data in the expected shape, or a broken local proxy or certificate setting), the server keeps answering from the data it already has. `data.py` catches every exception at this one point, because the list of specific types kept missing real cases (added 2026-10-23). New data is checked before it replaces the old. If there is no data at all (the first call after start-up, with GOV.UK down), the tool returns an error saying the data could not be got from GOV.UK.

**Why:** bank holidays rarely change, so day-old data is almost always right, and an error would be wrong far more often. If GOV.UK did change a holiday, a working cache could be up to 24 hours behind anyway. With no data at all, there is nothing honest to answer from. The cache lives in memory, so old data never outlives the server process.

### 4. GOV.UK calls time out after 5 seconds; after a failure, wait 1 hour before retrying (2026-10-20)

**Why:** without this, while GOV.UK is down every tool call would wait for the timeout before falling back to the old data (decision 3).

The 5 seconds is httpx's timeout, which limits each step (connecting, and each read of the response), not the whole download. GOV.UK's file is small and served from a CDN, so a limit on the whole request is not worth the extra code (added 2026-10-23).

The 1-hour wait applies only when there is old data to fall back on. With no data at all, every call tries GOV.UK again (added 2026-10-22), because a network blip at start-up must not leave the server returning errors for an hour.

There is no lock around the refresh. In mcp 2.x two tool calls can run at once, so both may download GOV.UK when the cache expires. That is harmless, and not worth the extra code.

### 5. "Next" includes `from_date` itself (2026-10-20)

On 25 December, `next_bank_holiday()` returns 25 December with `days_away: 0`. `next_bank_holiday(from_date='2027-01-01')` returns New Year's Day, 1 January 2027.

**Why:** "from" reads as "from and including", and `count_working_days` already includes both its dates, so every date argument means the same thing. Excluding `from_date` would skip the very holiday a user is asking about. (First answered as "strictly after", then changed after testing the 1 January case.)

### 6. `division` is required, with no default (2026-10-20)

Every tool that takes `division` requires it. This replaces the `england-and-wales` default in CLAUDE.md.

**Why:** with a default, `is_bank_holiday('2026-11-30')` for a user in Scotland answers "No", but it is St Andrew's Day there. That is the same confident wrong answer decisions 1 and 2 prevent. Requiring `division` makes the agent think about the user's region.

### 7. Every returned holiday includes GOV.UK's `notes`, unchanged (2026-10-20)

`list_bank_holidays`, `next_bank_holiday` and `is_bank_holiday` return `notes` next to `title`, exactly as GOV.UK gives it. On 2026-10-20 its only values are `''` and `'Substitute day'`.

**Why:** GOV.UK titles a substitute day after the holiday it replaces, e.g. 2027-12-27 is titled "Christmas Day". Without `notes`, an agent would say Christmas Day is on 27 December. Passing `notes` through unchanged is simpler than a yes/no `substitute_day` field, and any new kind of note GOV.UK adds still gets through.

### 8. "Today" is the date in the UK (`Europe/London`), not the computer's date (2026-10-20)

`next_bank_holiday()` with no `from_date` uses today's UK date. This adds the `tzdata` package, because Windows has no built-in time zone data.

**Why:** UK bank holidays fall on UK dates. At 07:30 on 25 December in Hong Kong it is still 24 December in London, so Christmas is `days_away: 1`, not 0.

### 9. No next holiday inside the data is an error (2026-10-20)

`next_bank_holiday(from_date='2028-12-27')` returns an error saying which years the data covers (it ends in 2028), even though 2028 is a covered year.

**Why:** the next holiday would be in 2029, which has no data. Same rule as decision 1: "unknown" must not look like an answer.

### 10. `list_bank_holidays` with no `year` lists the current UK year (2026-10-20)

**Why:** users usually mean this year, and all covered years is about 83 to 103 holidays for an agent to read. "Current" uses the UK date, as in decision 8.

### 11. Tool and argument descriptions live in code, not docstrings (2026-10-20)

Each tool's description goes in `@mcp.tool(description='...')`; each argument's in `Annotated[<type>, Field(description='...')]`.

**Why:** `~/wyatt/CLAUDE.md` Rule 6 bans docstrings, but `MCPServer` takes a tool's description from its docstring by default, and agents need those descriptions. This keeps both.

### 12. Errors are raised, so they reach the agent as MCP errors (2026-10-20)

A tool raises `ToolError` with a clear message; `MCPServer` returns it as a tool error (`isError: true`), not as a normal result with an error field in it. `test_server.py` checks this.

**Why:** an error that looks like a normal result can be read as data. Every "unknown" in decisions 1, 2 and 9 depends on the agent seeing it as an error. It must be `ToolError` specifically: in mcp 2.x an `MCPError` becomes a protocol-level failure instead, which the agent may not see as a message to act on.

### 13. Use mcp 2.x (`MCPServer`) and `httpx2` (2026-10-20)

`mcp[cli]>=2.3,<3`, with `MCPServer` from `mcp.server.mcpserver`. GOV.UK is fetched with `httpx2`, the HTTP client mcp 2.x already uses.

**Why:** a new project should start on the current API, not the outgoing 1.x line. `@mcp.tool(...)` takes the same arguments as 1.x, so decision 11 still works. Using `httpx2` (same API as `httpx`) avoids a second HTTP library. In 2.x, normal `def` tools run in a worker thread, so a slow GOV.UK call does not freeze the server. Downside: most tutorials still show 1.x `FastMCP`.

### 14. Redirects from GOV.UK are not followed (2026-10-23)

`data.py` does not follow redirects. A redirect counts as a failed fetch, so decision 3 keeps the old data.

**Why:** GOV.UK has served this URL for years and does not redirect it. Following redirects safely would mean checking every hop for HTTPS before its request is sent, and redirects multiply the 5-second timeout: review rounds on 23 Oct found each of these problems. If GOV.UK ever moves the file, the server keeps its old data, and `GOV_UK_URL` in `data.py` is a one-line change. (Redirects were briefly followed on 23 Oct, then this was reverted.)

### 15. Date arguments must be real dates written exactly as YYYY-MM-DD (2026-10-23)

`validators.py` parses every date argument itself: it must be text, a real date, and read back exactly as written. Numbers, Unix timestamps (as numbers or text), date-times and impossible dates such as `2027-02-30` all get the same clear error.

**Why:** pydantic's default date parsing is loose. It read `1798761600` as 1 January 2027 and `2026-12-25T00:00:00Z` as 25 December, so the tools gave confident answers for dates nobody wrote: the problem decision 1 exists to prevent. `data.py` checks GOV.UK's own dates with the same function.

### 16. An unknown argument name is an error (2026-10-23)

The server rejects a tool call that uses an argument name the tool does not have, and the error lists the names it does take. One middleware function in `server.py` does this for every tool, using each tool's own schema, so new tools and arguments are covered automatically.

**Why:** the mcp 2.x SDK silently drops unknown names, so a typo fell back to the default. `next_bank_holiday` with `date` instead of `from_date` answered for today, and `years: 2030` listed this year instead of saying there is no data: the confident wrong answer decision 1 exists to prevent. mcp 2.x marks its middleware API as provisional; if an update changes it, `test_server.py` fails loudly.
