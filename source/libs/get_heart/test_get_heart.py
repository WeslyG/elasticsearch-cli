from .get_heart import get_heart


def test_green_heart():
    assert get_heart("green") == "💚"


def test_yellow_heart():
    assert get_heart("yellow") == "💛"


def test_red_heart():
    assert get_heart("red") == "❤️"


def test_bool_heart():
    assert get_heart(True) == False

# def test_color_below_zero():
#   assert get_color(-2) == 'Exception'
