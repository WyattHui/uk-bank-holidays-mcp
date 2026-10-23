import datetime
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from importlib.metadata import version
from typing import Annotated

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BeforeValidator, Field

from uk_bank_holidays_mcp import holidays
from uk_bank_holidays_mcp.data import BankHolidayData
from uk_bank_holidays_mcp.holidays import (
    BankHolidayError,
    DayCheck,
    Division,
    Holiday,
    NextHoliday,
    uk_today,
)
from uk_bank_holidays_mcp.validators import parse_date_text

mcp = MCPServer('uk-bank-holidays', version=version('uk-bank-holidays-mcp'))
bank_holiday_data = BankHolidayData()

READ_ONLY = ToolAnnotations(read_only_hint=True)
IsoDate = Annotated[datetime.date, BeforeValidator(parse_date_text)]
DivisionArg = Annotated[Division, Field(
    description='UK region: england-and-wales, scotland or northern-ireland. Bank holidays '
    'differ between regions, so use the one the user lives or works in. If the region is not '
    'known, ask the user rather than assuming england-and-wales.'
)]
COVERAGE = (
    'Returns an error, rather than guessing, for any date, year or part of a range in a year '
    'with no GOV.UK data, and when the data cannot be fetched from GOV.UK and none is cached.'
)
SUBSTITUTE_DAYS = (
    'When a holiday falls on a weekend, the day off moves to a weekday: that weekday has notes '
    '"Substitute day" and keeps the title of the original holiday, and the weekend date itself '
    'is not a bank holiday.'
)


@mcp.tool(
    description='List the UK bank holidays in one year for one region, from official GOV.UK '
    f'data. Each holiday has its date (YYYY-MM-DD), title and notes. {SUBSTITUTE_DAYS} '
    f'{COVERAGE}',
    annotations=READ_ONLY,
)
def list_bank_holidays(
    division: DivisionArg,
    year: Annotated[int | None, Field(
        description='Four-digit year, e.g. 2027. Defaults to the current year in the UK.'
    )] = None,
) -> list[Holiday]:
    with _tool_errors():
        year = year if year is not None else _today().year
        return holidays.list_bank_holidays(bank_holiday_data.get(), division, year)


@mcp.tool(
    description='Find the next UK bank holiday on or after a date, for one region, from '
    'official GOV.UK data. Returns its date, title, notes and days_away (calendar days from '
    'from_date; 0 means the date itself is a bank holiday). '
    f'{SUBSTITUTE_DAYS} {COVERAGE} Also returns an error if no '
    'later bank holiday is in the data yet.',
    annotations=READ_ONLY,
)
def next_bank_holiday(
    division: DivisionArg,
    from_date: Annotated[IsoDate | None, Field(
        description='Search from this date (YYYY-MM-DD); the date itself counts. Defaults to '
        'today in the UK.'
    )] = None,
) -> NextHoliday:
    with _tool_errors():
        from_date = from_date if from_date is not None else _today()
        return holidays.next_bank_holiday(bank_holiday_data.get(), division, from_date)


@mcp.tool(
    description='Check whether a date is a UK bank holiday in one region, from official '
    'GOV.UK data. Returns is_bank_holiday, plus the title and notes of the holiday if it is '
    'one (both null if it is not). '
    f'{SUBSTITUTE_DAYS} {COVERAGE}',
    annotations=READ_ONLY,
)
def is_bank_holiday(
    date: Annotated[IsoDate, Field(description='The date to check, as YYYY-MM-DD.')],
    division: DivisionArg,
) -> DayCheck:
    with _tool_errors():
        return holidays.is_bank_holiday(bank_holiday_data.get(), division, date)


@mcp.tool(
    description='Count the working days between two dates in one UK region: weekdays that '
    'are not bank holidays, with both dates included. Uses official GOV.UK data. Returns the '
    f'number of working days. {COVERAGE} Also returns an error if start is after end.',
    annotations=READ_ONLY,
)
def count_working_days(
    start: Annotated[IsoDate, Field(
        description='First day of the range, YYYY-MM-DD; it is included in the count.'
    )],
    end: Annotated[IsoDate, Field(
        description='Last day of the range, YYYY-MM-DD; it is included in the count.'
    )],
    division: DivisionArg,
) -> int:
    with _tool_errors():
        return holidays.count_working_days(bank_holiday_data.get(), division, start, end)


async def _reject_unknown_arguments(
    ctx: ServerRequestContext, call_next: CallNext
) -> HandlerResult:
    params = ctx.params if isinstance(ctx.params, Mapping) else {}
    name, arguments = params.get('name'), params.get('arguments') or {}
    is_normal_call = isinstance(name, str) and isinstance(arguments, Mapping)
    if ctx.method != 'tools/call' or not is_normal_call:
        return await call_next(ctx)
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    tool = tools.get(name)
    if tool is None:
        return await call_next(ctx)
    allowed = sorted(tool.input_schema['properties'])
    unknown = sorted(set(arguments) - set(allowed))
    if not unknown:
        return await call_next(ctx)
    given, valid = ', '.join(unknown), ', '.join(allowed)
    message = f'Unknown argument: {given}. {tool.name} takes: {valid}.'
    return CallToolResult(content=[TextContent(type='text', text=message)], is_error=True)


mcp.middleware.append(_reject_unknown_arguments)


@contextmanager
def _tool_errors() -> Iterator[None]:
    try:
        yield
    except BankHolidayError as error:
        raise ToolError(str(error)) from error


def _today() -> datetime.date:
    return uk_today(datetime.datetime.now(datetime.UTC))


if __name__ == '__main__':
    mcp.run()
