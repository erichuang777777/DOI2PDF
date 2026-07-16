from doi2pdf.batch_plan import batch_group_for, group_items


def test_batch_groups_follow_known_route_labels_and_unknown_prefixes():
    items = [
        {"doi": "10.1056/NEJMoa1", "title": "NEJM"},
        {"doi": "10.1016/j.ipm.2025.104216", "title": "Elsevier"},
        {"doi": None, "title": "Untitled"},
    ]
    assert batch_group_for(items[0]) == "nejm"
    assert batch_group_for(items[1]) == "10.1016"
    assert batch_group_for(items[2]).startswith("title:")
    grouped = group_items(items)
    assert set(grouped) == {"nejm", "10.1016", batch_group_for(items[2])}
