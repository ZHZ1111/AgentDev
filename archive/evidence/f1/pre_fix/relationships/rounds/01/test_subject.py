from subject import calculate_total, checkout


def test_unit_calculate_total_normal():
    assert calculate_total(12, 3) == 36


def test_unit_calculate_total_boundary():
    assert calculate_total(0, 5) == 0


def test_collaboration_checkout_normal():
    assert checkout(12, 3) == 36


def test_collaboration_checkout_boundary():
    assert checkout(12, 0) == 0
