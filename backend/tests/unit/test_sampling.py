from app.domain.sampling import stratify


def test_takes_up_to_n_from_each_group():
    items = ([("a", i) for i in range(20)] + [("b", i) for i in range(3)]
             + [("c", i) for i in range(10)])
    out = stratify(items, key=lambda x: x[0], per_group=5)
    counts = {g: sum(1 for i in out if i[0] == g) for g in "abc"}
    assert counts == {"a": 5, "b": 3, "c": 5}


def test_preserves_input_order_within_a_group():
    items = [("a", 3), ("a", 1), ("a", 2)]
    assert stratify(items, key=lambda x: x[0], per_group=2) == [("a", 3), ("a", 1)]


def test_items_with_no_group_are_excluded():
    items = [("a", 1), (None, 2)]
    assert stratify(items, key=lambda x: x[0], per_group=5) == [("a", 1)]
