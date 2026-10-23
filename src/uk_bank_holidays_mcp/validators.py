from datetime import date

BAD_DATE = 'must be a real date written as YYYY-MM-DD, e.g. 2027-12-25'


def parse_date_text(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError(BAD_DATE)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(BAD_DATE) from None
    if parsed.isoformat() != value:
        raise ValueError(BAD_DATE)
    return parsed
