from .get_color import get_color


def test_color_more_zero():
    assert get_color(2) == 'red'


def test_color_on_zero():
    assert get_color(0) == 'green'

# def test_color_no_number():
#   assert get_color('null') == 'Exception'

# def test_color_below_zero():
#   assert get_color(-2) == 'Exception'
