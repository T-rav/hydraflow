def test_to_hex():
    from src.color import to_hex

    assert to_hex((255, 0, 0)) == "#ff0000"
