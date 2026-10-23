import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from uk_bank_holidays_mcp.holidays import (
    BankHolidayError,
    count_working_days,
    is_bank_holiday,
    list_bank_holidays,
    next_bank_holiday,
    uk_today,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'bank-holidays.json'
DATA = json.loads(FIXTURE.read_text(encoding='utf-8'))


def test_list_returns_one_year_with_notes():
    holidays = list_bank_holidays(DATA, 'england-and-wales', 2027)

    assert len(holidays) == 8
    assert all(h['date'].startswith('2027-') for h in holidays)
    # Decision 7: without notes, an agent would say Christmas Day is on 27 December.
    assert {'date': '2027-12-27', 'title': 'Christmas Day', 'notes': 'Substitute day'} in holidays


def test_list_year_outside_data_is_an_error():
    with pytest.raises(BankHolidayError, match='covers 2026 to 2028'):
        list_bank_holidays(DATA, 'england-and-wales', 2030)


def test_next_includes_from_date_itself():
    # Decision 5: a user asking "from 1 January" must not miss New Year's Day.
    result = next_bank_holiday(DATA, 'england-and-wales', date(2027, 1, 1))

    assert result == {'date': '2027-01-01', 'title': 'New Year’s Day', 'notes': '', 'days_away': 0}


def test_events_are_used_in_date_order_whatever_order_gov_uk_sends():
    # next_bank_holiday takes the first holiday on or after the date, so it must not rely on
    # GOV.UK listing its events in order: a one-off holiday could be added at the end.
    reversed_data = copy.deepcopy(DATA)
    reversed_data['england-and-wales']['events'].reverse()

    upcoming = next_bank_holiday(reversed_data, 'england-and-wales', date(2026, 12, 24))
    dates = [h['date'] for h in list_bank_holidays(reversed_data, 'england-and-wales', 2027)]

    assert (upcoming['date'], upcoming['days_away']) == ('2026-12-25', 1)
    assert dates == sorted(dates)


def test_next_counts_days_away():
    result = next_bank_holiday(DATA, 'england-and-wales', date(2026, 12, 24))

    assert result['date'] == '2026-12-25'
    assert result['days_away'] == 1


def test_next_with_no_holiday_left_in_data_is_an_error():
    # Decision 9: 2028 is covered, but the next holiday would be in 2029, which is unknown.
    with pytest.raises(BankHolidayError, match='on or after 2028-12-27 .* covers 2026 to 2028'):
        next_bank_holiday(DATA, 'england-and-wales', date(2028, 12, 27))


def test_next_from_date_outside_data_is_an_error():
    with pytest.raises(BankHolidayError, match='covers 2026 to 2028'):
        next_bank_holiday(DATA, 'england-and-wales', date(2030, 1, 1))


def test_is_bank_holiday_returns_title_and_notes():
    result = is_bank_holiday(DATA, 'england-and-wales', date(2026, 12, 28))

    assert result == {
        'date': '2026-12-28',
        'is_bank_holiday': True,
        'title': 'Boxing Day',
        'notes': 'Substitute day',
    }


def test_is_bank_holiday_depends_on_division():
    # Decision 6: the same date has different answers in Scotland and England.
    scotland = is_bank_holiday(DATA, 'scotland', date(2026, 11, 30))
    england = is_bank_holiday(DATA, 'england-and-wales', date(2026, 11, 30))

    assert scotland['title'] == 'St Andrew’s Day'
    assert england['is_bank_holiday'] is False


def test_is_bank_holiday_after_last_listed_holiday_is_no_not_an_error():
    # Decision 1: 2028 is a covered year, so 29 December is known not to be a holiday.
    result = is_bank_holiday(DATA, 'england-and-wales', date(2028, 12, 29))

    assert result == {'date': '2028-12-29', 'is_bank_holiday': False, 'title': None, 'notes': None}


def test_is_bank_holiday_outside_data_is_an_error_not_no():
    # Decision 1: a "No" for an unknown year would be a confident wrong answer.
    with pytest.raises(BankHolidayError, match='No data for 2030'):
        is_bank_holiday(DATA, 'england-and-wales', date(2030, 12, 25))


def test_count_skips_weekends_and_bank_holidays():
    # 10 weekdays; 25 Dec, 28 Dec (Boxing Day substitute) and 1 Jan are bank holidays.
    assert count_working_days(DATA, 'england-and-wales', date(2026, 12, 21), date(2027, 1, 1)) == 7


def test_count_includes_both_start_and_end():
    monday = date(2026, 12, 21)

    assert count_working_days(DATA, 'england-and-wales', monday, monday) == 1


def test_count_uses_the_division():
    # St Andrew's Day, Monday 30 November 2026, is a bank holiday only in Scotland.
    monday = date(2026, 11, 30)

    assert count_working_days(DATA, 'scotland', monday, monday) == 0
    assert count_working_days(DATA, 'england-and-wales', monday, monday) == 1


def test_count_range_partly_outside_data_is_an_error():
    # Decision 2: a partial count would look like a full answer.
    with pytest.raises(BankHolidayError, match='No data for 2029'):
        count_working_days(DATA, 'england-and-wales', date(2028, 12, 1), date(2029, 1, 31))


def test_count_start_after_end_is_an_error():
    with pytest.raises(BankHolidayError, match='after end'):
        count_working_days(DATA, 'england-and-wales', date(2027, 1, 2), date(2027, 1, 1))


def test_unknown_division_lists_the_valid_ones():
    with pytest.raises(BankHolidayError, match='england-and-wales, scotland, northern-ireland'):
        is_bank_holiday(DATA, 'wales', date(2027, 1, 1))


def test_uk_today_uses_the_london_date_not_the_local_one():
    # Decision 8: 07:30 on 25 December in Hong Kong is still 24 December in the UK.
    hong_kong_morning = datetime(2026, 12, 25, 7, 30, tzinfo=ZoneInfo('Asia/Hong_Kong'))

    assert uk_today(hong_kong_morning) == date(2026, 12, 24)


def test_uk_today_follows_british_summer_time():
    # 23:30 UTC on 30 June is 00:30 on 1 July in London, so the UK date has already moved on.
    assert uk_today(datetime(2026, 6, 30, 23, 30, tzinfo=timezone.utc)) == date(2026, 7, 1)
