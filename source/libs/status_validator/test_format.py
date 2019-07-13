from .status import status_validator


def test_validator_green():
    assert status_validator('green') == 'green'


def test_validator_yellow():
    assert status_validator('yellow') == 'yellow'


def test_validator_red():
    assert status_validator('red') == 'red'


def test_validator_g():
    assert status_validator('g') == 'green'


def test_validator_y():
    assert status_validator('y') == 'yellow'


def test_validator_r():
    assert status_validator('r') == 'red'


def test_validator_string():
    assert status_validator('yqwe') == 'Bad status value'


def test_validator_none():
    assert status_validator(None) is None


def test_validator_int():
    assert status_validator(11) == 'Bad status value'


def test_validator_obj():
    assert status_validator({}) == 'Bad status value'


def test_validator_arr():
    assert status_validator([]) == 'Bad status value'
