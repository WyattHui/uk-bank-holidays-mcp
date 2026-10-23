import re
from datetime import date

import pytest

from uk_bank_holidays_mcp.validators import BAD_DATE, parse_date_text


def test_reads_a_date_written_as_yyyy_mm_dd():
    assert parse_date_text('2027-12-25') == date(2027, 12, 25)


@pytest.mark.parametrize('bad', [
    1798761600,
    '1798761600',
    '2026-12-25T00:00:00Z',
    '20271225',
    '2027-W01-5',
    '2027-02-30',
    '25/12/2026',
    None,
    date(2027, 12, 25),
])
def test_anything_else_is_rejected_with_the_same_message(bad):
    # Decision 15: only text written exactly as YYYY-MM-DD may become a date; a timestamp
    # such as 1798761600 (1 January 2027) or a date-time must never be read as one.
    with pytest.raises(ValueError, match=re.escape(BAD_DATE)):
        parse_date_text(bad)
