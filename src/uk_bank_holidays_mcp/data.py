import time
from collections.abc import Callable
from datetime import timedelta

import httpx2

from uk_bank_holidays_mcp.holidays import DIVISIONS, BankHolidayError
from uk_bank_holidays_mcp.validators import parse_date_text

GOV_UK_URL = 'https://www.gov.uk/bank-holidays.json'
TIMEOUT_SECONDS = 5
CACHE_SECONDS = timedelta(hours=24).total_seconds()
RETRY_WAIT_SECONDS = timedelta(hours=1).total_seconds()


class BankHolidayData:
    def __init__(
        self,
        fetch: Callable[[], dict] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._fetch = fetch or _fetch_from_gov_uk
        self._clock = clock
        self._data = None
        self._fetched_at = None
        self._failed_at = None

    def get(self) -> dict:
        now = self._clock()
        if self._should_fetch(now):
            self._try_fetch(now)
        if self._data is None:
            raise BankHolidayError(
                f'Could not get bank holiday data from GOV.UK ({GOV_UK_URL}). Try again later.'
            )
        return self._data

    def _should_fetch(self, now: float) -> bool:
        if self._data is None:
            return True
        if now - self._fetched_at < CACHE_SECONDS:
            return False
        failed_at = self._failed_at
        return failed_at is None or now - failed_at >= RETRY_WAIT_SECONDS

    def _try_fetch(self, now: float) -> None:
        try:
            fetched = self._fetch()
            _check_shape(fetched)
        except Exception:
            self._failed_at = now
            return
        self._fetched_at = now
        self._failed_at = None
        self._data = fetched


def _fetch_from_gov_uk() -> dict:
    response = httpx2.get(GOV_UK_URL, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _check_shape(fetched: dict) -> None:
    for division in DIVISIONS:
        events = fetched[division]['events']
        if not events:
            raise ValueError(f'GOV.UK data has no {division} bank holidays')
        for event in events:
            parse_date_text(event['date'])
            if not (isinstance(event['title'], str) and isinstance(event['notes'], str)):
                raise ValueError(f'GOV.UK event has no text title or notes: {event!r}')
