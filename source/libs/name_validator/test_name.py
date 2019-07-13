from .name_valid import name_validator


def name_validator_all():
    assert name_validator('all') == 'all'


def name_validator_pri():
    assert name_validator('primaries') == 'primaries'


def name_validator_new_pri():
    assert status_validator('new_primaries') == 'new_primaries'


def name_validator_disable():
    assert status_validator('disable') == 'null'


def name_validator_enable():
    assert status_validator('enable') == 'all'


def name_validator_string():
    assert status_validator('test') == 'Bad status value'


def name_validator_none():
    assert status_validator(None) == 'Bad status value'


def name_validator_obj():
    assert status_validator({}) == 'Bad status value'


def name_validator_arr():
    assert status_validator([]) == 'Bad status value'


def name_validator_int():
    assert status_validator(123) == 'Bad status value'
