def test_square():
    from src.math_util import square

    assert square(3) == 9
    assert square(-2) == 4
    assert square(0) == 0
