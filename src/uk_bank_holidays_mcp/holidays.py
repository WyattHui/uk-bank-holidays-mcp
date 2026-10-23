from calendar import SATURDAY, SUNDAY
from datetime import date, datetime, timedelta
from typing import Literal, TypedDict, get_args
from zoneinfo import ZoneInfo

Division = Literal['england-and-wales', 'scotland', 'northern-ireland']
DIVISIONS = get_args(Division)
UK_TIME_ZONE = ZoneInfo('Europe/London')


class BankHolidayError(ValueError):
    pass


class Holiday(TypedDict):
    date: str
    title: str
    notes: str


class NextHoliday(Holiday):
    days_away: int


class DayCheck(TypedDict):
    date: str
    is_bank_holiday: bool
    title: str | None
    notes: str | None


def list_bank_holidays(data: dict, division: str, year: int) -> list[Holiday]:
    events = _events(data, division)
    _require_covered_year(year, events)
    return [_holiday(event) for event in events if _event_date(event).year == year]


def next_bank_holiday(data: dict, division: str, from_date: date) -> NextHoliday:
    events = _events(data, division)
    _require_covered_year(from_date.year, events)
    for event in events:
        day = _event_date(event)
        if day >= from_date:
            return {**_holiday(event), 'days_away': (day - from_date).days}
    covered = _covered_years(events)
    raise BankHolidayError(
        f'No bank holiday on or after {from_date} in the GOV.UK data, which covers '
        f'{min(covered)} to {max(covered)}.'
    )


def is_bank_holiday(data: dict, division: str, day: date) -> DayCheck:
    events = _events(data, division)
    _require_covered_year(day.year, events)
    event = next((event for event in events if _event_date(event) == day), None)
    return {
        'date': day.isoformat(),
        'is_bank_holiday': event is not None,
        'title': event['title'] if event else None,
        'notes': event['notes'] if event else None,
    }


def count_working_days(data: dict, division: str, start: date, end: date) -> int:
    if start > end:
        raise BankHolidayError(f'start ({start}) is after end ({end}).')
    events = _events(data, division)
    for year in range(start.year, end.year + 1):
        _require_covered_year(year, events)
    holidays = {_event_date(event) for event in events}
    days = (start + timedelta(days=offset) for offset in range((end - start).days + 1))
    weekdays = [day for day in days if day.weekday() not in (SATURDAY, SUNDAY)]
    return len([day for day in weekdays if day not in holidays])


def uk_today(now: datetime) -> date:
    return now.astimezone(UK_TIME_ZONE).date()


def _events(data: dict, division: str) -> list[dict]:
    if division not in DIVISIONS:
        valid = ', '.join(DIVISIONS)
        raise BankHolidayError(f'Unknown division {division!r}. Valid divisions: {valid}.')
    return sorted(data[division]['events'], key=lambda event: event['date'])


def _require_covered_year(year: int, events: list[dict]) -> None:
    covered = _covered_years(events)
    if year not in covered:
        raise BankHolidayError(
            f'No data for {year}. The GOV.UK data covers {min(covered)} to {max(covered)}.'
        )


def _covered_years(events: list[dict]) -> set[int]:
    return {_event_date(event).year for event in events}


def _holiday(event: dict) -> Holiday:
    return {'date': event['date'], 'title': event['title'], 'notes': event['notes']}


def _event_date(event: dict) -> date:
    return date.fromisoformat(event['date'])
