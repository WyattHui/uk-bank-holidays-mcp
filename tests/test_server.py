import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from uk_bank_holidays_mcp import server
from uk_bank_holidays_mcp.data import BankHolidayData
from uk_bank_holidays_mcp.validators import BAD_DATE

FIXTURE = Path(__file__).parent / 'fixtures' / 'bank-holidays.json'
DATA = json.loads(FIXTURE.read_text(encoding='utf-8'))

RUN_SERVER_WITH_FIXTURE_DATA = '''
import json, sys
from uk_bank_holidays_mcp import server
from uk_bank_holidays_mcp.data import BankHolidayData
fixture = json.load(open(sys.argv[1], encoding='utf-8'))
server.bank_holiday_data = BankHolidayData(fetch=lambda: fixture)
server.mcp.run()
'''
SERVER = StdioServerParameters(
    command=sys.executable, args=['-c', RUN_SERVER_WITH_FIXTURE_DATA, str(FIXTURE)]
)
TOOL_NAMES = {'list_bank_holidays', 'next_bank_holiday', 'is_bank_holiday', 'count_working_days'}
HOLIDAY_TOOLS = {'list_bank_holidays', 'next_bank_holiday', 'is_bank_holiday'}


def test_lists_the_four_read_only_tools_that_require_a_division():
    tools = with_server(lambda client: client.list_tools()).tools

    assert {tool.name for tool in tools} == TOOL_NAMES
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        # Decision 6: an agent must always choose the user's region.
        assert 'division' in tool.input_schema['required']


def test_every_tool_and_argument_is_described_for_agents():
    tools = with_server(lambda client: client.list_tools()).tools

    for tool in tools:
        # Decision 11: descriptions come from code, not docstrings, so check they arrived.
        assert tool.description
        assert tool.output_schema
        for argument in tool.input_schema['properties'].values():
            assert argument['description']
        if tool.name in HOLIDAY_TOOLS:
            # Decision 7: agents must know a substitute day keeps the original holiday's title.
            assert 'Substitute day' in tool.description


def test_tools_return_complete_structured_results():
    async def steps(client):
        return [
            await client.call_tool('list_bank_holidays', {'division': 'scotland', 'year': 2027}),
            await client.call_tool(
                'next_bank_holiday', {'division': 'england-and-wales', 'from_date': '2027-01-01'}
            ),
            await client.call_tool(
                'is_bank_holiday', {'date': '2026-11-30', 'division': 'scotland'}
            ),
            await client.call_tool(
                'is_bank_holiday', {'date': '2026-12-24', 'division': 'england-and-wales'}
            ),
            await client.call_tool(
                'count_working_days',
                {'start': '2026-12-21', 'end': '2027-01-01', 'division': 'england-and-wales'},
            ),
        ]

    listed, upcoming, holiday, not_holiday, counted = with_server(steps)

    assert listed.structured_content == {'result': [
        {'date': event['date'], 'title': event['title'], 'notes': event['notes']}
        for event in DATA['scotland']['events']
        if event['date'].startswith('2027-')
    ]}
    assert upcoming.structured_content == {
        'date': '2027-01-01', 'title': 'New Year’s Day', 'notes': '', 'days_away': 0,
    }
    assert holiday.structured_content == {
        'date': '2026-11-30', 'is_bank_holiday': True, 'title': 'St Andrew’s Day', 'notes': '',
    }
    # A "No" is the only result with null title and notes, so the output schema must allow it.
    assert not_holiday.structured_content == {
        'date': '2026-12-24', 'is_bank_holiday': False, 'title': None, 'notes': None,
    }
    assert counted.structured_content == {'result': 7}


def test_bank_holiday_error_reaches_the_agent_with_its_message():
    # Decision 12: in mcp 2.x only a ToolError's text reaches the agent; anything else is hidden.
    result = with_server(lambda client: client.call_tool(
        'is_bank_holiday', {'date': '2030-12-25', 'division': 'england-and-wales'}
    ))

    assert result.is_error is True
    assert 'No data for 2030. The GOV.UK data covers 2026 to 2028.' in result.content[0].text


def test_every_tool_reports_its_data_errors_to_the_agent():
    # Decisions 2, 9 and 12: each tool must convert its errors, or the agent sees no reason.
    data_errors = [
        ('list_bank_holidays', {'division': 'scotland', 'year': 2030}, 'covers 2026 to 2028'),
        (
            'next_bank_holiday',
            {'division': 'scotland', 'from_date': '2028-12-27'},
            'No bank holiday on or after 2028-12-27',
        ),
        (
            'count_working_days',
            {'start': '2028-12-01', 'end': '2029-01-31', 'division': 'scotland'},
            'No data for 2029',
        ),
        (
            'count_working_days',
            {'start': '2027-01-02', 'end': '2027-01-01', 'division': 'scotland'},
            'after end',
        ),
    ]

    async def steps(client):
        return [await client.call_tool(name, arguments) for name, arguments, _ in data_errors]

    for (name, _, message), result in zip(data_errors, with_server(steps)):
        assert result.is_error is True, name
        assert message in result.content[0].text, name


def test_invalid_arguments_are_rejected_with_a_clear_message():
    # One bad value per date argument proves the strict check is wired into every tool;
    # test_validators.py owns the full list of rejected forms.
    bad_date_calls = [
        ('is_bank_holiday', {'date': '1798761600', 'division': 'scotland'}),
        ('next_bank_holiday', {'division': 'scotland', 'from_date': 1798761600}),
        (
            'count_working_days',
            {'start': '2026-12-25T00:00:00Z', 'end': '2027-01-05', 'division': 'scotland'},
        ),
        (
            'count_working_days',
            {'start': '2027-01-04', 'end': 1798761600, 'division': 'scotland'},
        ),
    ]

    async def steps(client):
        bad_division = await client.call_tool(
            'is_bank_holiday', {'date': '2026-11-30', 'division': 'wales'}
        )
        results = [await client.call_tool(name, arguments) for name, arguments in bad_date_calls]
        return bad_division, results

    bad_division, results = with_server(steps)

    assert bad_division.is_error is True
    assert "'england-and-wales', 'scotland' or 'northern-ireland'" in bad_division.content[0].text
    # Decision 15: in every date argument, a timestamp (1798761600 is 1 January 2027) or a
    # date-time must not silently become a date the agent never wrote.
    for call, result in zip(bad_date_calls, results):
        assert result.is_error is True, call
        assert BAD_DATE in result.content[0].text, call


def test_misspelled_argument_is_an_error_not_ignored():
    async def steps(client):
        return (
            await client.call_tool(
                'next_bank_holiday', {'division': 'scotland', 'date': '2027-06-01'}
            ),
            await client.call_tool('list_bank_holidays', {'division': 'scotland', 'years': 2030}),
        )

    wrong_date_name, wrong_year_name = with_server(steps)

    # Decision 16: an ignored typo would quietly answer for the default (today, this year).
    assert wrong_date_name.is_error is True
    assert wrong_date_name.content[0].text == (
        'Unknown argument: date. next_bank_holiday takes: division, from_date.'
    )
    assert wrong_year_name.is_error is True
    assert 'Unknown argument: years.' in wrong_year_name.content[0].text


def test_defaults_use_todays_date_in_the_uk(monkeypatch):
    monkeypatch.setattr(server, 'bank_holiday_data', BankHolidayData(fetch=lambda: DATA))
    monkeypatch.setattr(server, '_today', lambda: date(2027, 12, 24))

    # Decisions 8 and 10: with no date or year given, "today" and "this year" are the UK's.
    assert server.next_bank_holiday('england-and-wales')['date'] == '2027-12-27'
    assert {h['date'][:4] for h in server.list_bank_holidays('england-and-wales')} == {'2027'}


def test_today_is_the_uk_date_not_the_utc_or_local_one(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 30, 23, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(server.datetime, 'datetime', FrozenDateTime)

    # Decision 8: 23:30 UTC on 30 June is already 00:30 on 1 July in London (BST).
    assert server._today() == date(2026, 7, 1)


@pytest.mark.parametrize('name, arguments', [
    ('list_bank_holidays', {'division': 'scotland', 'year': 2027}),
    ('next_bank_holiday', {'division': 'scotland', 'from_date': '2027-01-01'}),
    ('is_bank_holiday', {'date': '2027-01-01', 'division': 'scotland'}),
    ('count_working_days', {'start': '2027-01-04', 'end': '2027-01-08', 'division': 'scotland'}),
])
def test_gov_uk_unavailable_with_nothing_cached_reaches_the_agent(monkeypatch, name, arguments):
    def gov_uk_down():
        raise httpx2.ConnectError('GOV.UK is down')

    monkeypatch.setattr(server, 'bank_holiday_data', BankHolidayData(fetch=gov_uk_down))

    async def main():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)

    result = anyio.run(main)

    # Decisions 3 and 12: with no data at all, the agent must be told why there is no answer.
    assert result.is_error is True
    assert 'Could not get bank holiday data from GOV.UK' in result.content[0].text


@pytest.mark.parametrize('params', [
    {'name': 'is_bank_holiday', 'arguments': '{"date": "2027-01-01", "division": "scotland"}'},
    {'name': 'is_bank_holiday', 'arguments': 5},
    {'name': ['is_bank_holiday'], 'arguments': {}},
    'not an object',
])
def test_malformed_calls_are_left_to_the_library_to_reject(params):
    passed_on = object()

    async def call_next(ctx):
        return passed_on

    async def check():
        ctx = SimpleNamespace(method='tools/call', params=params)
        return await server._reject_unknown_arguments(ctx, call_next)

    # The typo check judges only a normal arguments object; anything else must reach the
    # library's own "invalid params" error, not a misleading "unknown argument" one.
    assert anyio.run(check) is passed_on


def with_server(steps):
    async def main():
        async with Client(SERVER) as client:
            return await steps(client)

    return anyio.run(main)
