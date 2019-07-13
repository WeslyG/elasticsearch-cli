from .timeout import timeout_validator


def test_timeout_with_sec():
    assert timeout_validator('120s') == '120s'


def test_timeout_without_sec():
    assert timeout_validator('120') == '120s'


# def test_timeout_not_int():
#     assert timeout('sea') == '120s'
