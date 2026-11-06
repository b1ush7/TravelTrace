from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.mysql import dialect

from app.db.types import UTCDateTime


def test_mysql_datetimes_are_saved_in_utc_and_return_with_timezone():
    dt = UTCDateTime()
    local = datetime(2026, 11, 6, 12, 0, 0, 123456, tzinfo=timezone(timedelta(hours=8)))
    stored = dt.process_bind_param(local, dialect())
    assert stored == datetime(2026, 11, 6, 4, 0, 0, 123456)
    restored = dt.process_result_value(stored, dialect())
    assert restored == local and restored.tzinfo == timezone.utc


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        UTCDateTime().process_bind_param(datetime(2026, 11, 6), dialect())
