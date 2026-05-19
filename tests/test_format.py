from app.format import format_usage


def test_format_usage_zero():
    assert format_usage(0, 0, 0.0) == "session: ↑ 0 · ↓ 0 · $0.0000"


def test_format_usage_thousands_separator():
    assert format_usage(12400, 3100, 0.042) == "session: ↑ 12,400 · ↓ 3,100 · $0.0420"


def test_format_usage_four_decimal_cost():
    assert format_usage(1, 1, 0.0001) == "session: ↑ 1 · ↓ 1 · $0.0001"


def test_format_usage_rounds_cost_to_four_decimals():
    assert format_usage(0, 0, 0.123456) == "session: ↑ 0 · ↓ 0 · $0.1235"
