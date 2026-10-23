import copy
import json
from datetime import timedelta
from pathlib import Path

import httpx2
import pytest

from uk_bank_holidays_mcp import data
from uk_bank_holidays_mcp.data import BankHolidayData
from uk_bank_holidays_mcp.holidays import BankHolidayError

FIXTURE = Path(__file__).parent / 'fixtures' / 'bank-holidays.json'
OLD = json.loads(FIXTURE.read_text(encoding='utf-8'))
NEW = copy.deepcopy(OLD)
NEW['scotland']['events'] = NEW['scotland']['events'][:1]
UNREACHABLE = 'Could not get bank holiday data from GOV.UK'
REFRESH_FAILURES = [
    httpx2.ConnectError('GOV.UK is down'),
    FileNotFoundError(2, 'No such file or directory', '/missing/ca-bundle.pem'),
    ImportError('Using SOCKS proxy, but the socksio package is not installed.'),
    httpx2.InvalidURL('Invalid port'),
    RecursionError('maximum recursion depth exceeded'),
]


def test_data_is_cached_for_24_hours():
    gov_uk, clock = FakeGovUk(OLD), FakeClock()
    source = BankHolidayData(fetch=gov_uk, clock=clock)

    source.get()
    clock.advance(hours=23, minutes=59)

    # GOV.UK must not be called on every tool call.
    assert source.get() == OLD
    assert gov_uk.calls == 1


def test_data_is_refreshed_after_24_hours():
    gov_uk, clock = FakeGovUk(OLD, NEW), FakeClock()
    source = BankHolidayData(fetch=gov_uk, clock=clock)

    source.get()
    clock.advance(hours=24)

    assert source.get() == NEW


def test_failed_refresh_keeps_the_old_data():
    # Decision 3: day-old data is almost always right; an error would be wrong far more often.
    gov_uk, clock = FakeGovUk(OLD, down()), FakeClock()
    source = BankHolidayData(fetch=gov_uk, clock=clock)

    source.get()
    clock.advance(hours=24)

    assert source.get() == OLD


@pytest.mark.parametrize('failure', REFRESH_FAILURES)
def test_any_failed_refresh_keeps_the_old_data(failure):
    # Decision 3: whatever the cause, including a broken local proxy or certificate setting
    # (FileNotFoundError, ImportError, InvalidURL), a failed refresh falls back to the cache.
    gov_uk, clock = FakeGovUk(OLD, failure), FakeClock()
    source = BankHolidayData(fetch=gov_uk, clock=clock)

    source.get()
    clock.advance(hours=24)

    assert source.get() == OLD


@pytest.mark.parametrize('failure', REFRESH_FAILURES)
def test_any_failed_first_fetch_is_a_clear_error(failure):
    source = BankHolidayData(fetch=FakeGovUk(failure), clock=FakeClock())

    with pytest.raises(BankHolidayError, match=UNREACHABLE):
        source.get()


def test_invalid_json_from_gov_uk_keeps_the_old_data():
    gov_uk, clock = FakeGovUk(OLD, json.JSONDecodeError('not JSON', '<html>', 0)), FakeClock()
    source = BankHolidayData(fetch=gov_uk, clock=clock)

    source.get()
    clock.advance(hours=24)

    assert source.get() == OLD


@pytest.mark.parametrize('bad', [
    {'error': 'maintenance'},
    {**OLD, 'scotland': {'events': []}},
    {**OLD, 'scotland': {'events': [{'date': '2027-01-01', 'title': 'New Year’s Day'}]}},
    {**OLD, 'scotland': {'events': [{'date': '1/1/2027', 'title': 'x', 'notes': ''}]}},
    {**OLD, 'scotland': {'events': [{'date': '20270104', 'title': 'x', 'notes': ''}]}},
    {**OLD, 'scotland': {'events': [{'date': '2027-01-04', 'title': 'x', 'notes': None}]}},
    {**OLD, 'scotland': {'events': [{'date': '2027-01-04', 'title': 5, 'notes': ''}]}},
    ['not', 'a', 'dict'],
])
def test_wrong_shape_from_gov_uk_keeps_the_old_data(bad):
    # Decision 3: valid JSON in the wrong shape must not replace good data for 24 hours.
    gov_uk, clock = FakeGovUk(OLD, bad), FakeClock()
    source = BankHolidayData(fetch=gov_uk, clock=clock)

    source.get()
    clock.advance(hours=24)

    assert source.get() == OLD


def test_failed_refresh_waits_an_hour_before_retrying():
    # Decision 4: while GOV.UK is down, calls must not each wait for the timeout.
    gov_uk, clock = FakeGovUk(OLD, down(), NEW), FakeClock()
    source = BankHolidayData(fetch=gov_uk, clock=clock)

    source.get()
    clock.advance(hours=24)
    source.get()
    clock.advance(minutes=59)

    assert source.get() == OLD
    assert gov_uk.calls == 2

    clock.advance(minutes=1)

    assert source.get() == NEW


def test_no_data_and_gov_uk_down_is_an_error():
    # Decision 3: with no data at all, there is nothing honest to answer from.
    source = BankHolidayData(fetch=FakeGovUk(down()), clock=FakeClock())

    with pytest.raises(BankHolidayError, match=UNREACHABLE):
        source.get()


def test_with_no_data_every_call_retries():
    # A network blip at start-up must not leave the server answering errors for an hour.
    gov_uk = FakeGovUk(down(), OLD)
    source = BankHolidayData(fetch=gov_uk, clock=FakeClock())

    with pytest.raises(BankHolidayError):
        source.get()

    assert source.get() == OLD


def test_gov_uk_is_called_with_a_5_second_timeout_and_no_redirects(monkeypatch):
    calls = []

    def fake_get(url, **options):
        calls.append((url, options))
        return httpx2.Response(200, json=OLD, request=httpx2.Request('GET', url))

    monkeypatch.setattr(data.httpx2, 'get', fake_get)

    assert BankHolidayData().get() == OLD
    # Decision 14: redirects are not followed, so httpx2's default must not be overridden.
    assert calls == [('https://www.gov.uk/bank-holidays.json', {'timeout': 5})]


@pytest.mark.parametrize('response', [
    {'status_code': 503},
    {'status_code': 200, 'content': b'\xff\xfe not UTF-8'},
    {'status_code': 301, 'headers': {'location': 'http://example.org/bank-holidays.json'}},
])
def test_bad_gov_uk_response_counts_as_a_failure(monkeypatch, response):
    # Decision 14: a redirect is a failure too, never something to follow.
    def fake_get(url, **options):
        return httpx2.Response(**response, request=httpx2.Request('GET', url))

    monkeypatch.setattr(data.httpx2, 'get', fake_get)

    with pytest.raises(BankHolidayError, match=UNREACHABLE):
        BankHolidayData().get()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, **duration):
        self.now += timedelta(**duration).total_seconds()


class FakeGovUk:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def down():
    return httpx2.ConnectError('GOV.UK is down')
