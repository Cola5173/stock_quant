import pytest
from unittest.mock import MagicMock
from api.utils.retry import retry_call


def test_retry_succeeds_on_third_attempt():
    fn = MagicMock(side_effect=[Exception("1"), Exception("2"), "ok"])
    result = retry_call(fn, times=3, interval=0)
    assert result == "ok"
    assert fn.call_count == 3


def test_retry_raises_after_exhaustion():
    fn = MagicMock(side_effect=Exception("fail"))
    with pytest.raises(Exception, match="fail"):
        retry_call(fn, times=2, interval=0)
    assert fn.call_count == 2


def test_retry_first_success_no_retry():
    fn = MagicMock(return_value="done")
    result = retry_call(fn, times=3, interval=0)
    assert result == "done"
    assert fn.call_count == 1
