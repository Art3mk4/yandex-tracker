"""normalize_changelog / _chvalue: поля истории в человекочитаемый вид."""
from app.mirror import _chvalue, normalize_changelog


def test_dict_takes_display():
    assert _chvalue({"display": "В работе", "key": "inProgress"}) == "В работе"


def test_list_joined_with_comma():
    assert _chvalue([{"display": "A"}, {"display": "B"}]) == "A, B"


def test_none_and_scalar():
    assert _chvalue(None) == ""
    assert _chvalue(42) == "42"
    assert _chvalue("text") == "text"


def test_normalize_changelog_fields():
    fields = [
        {"field": "Статус", "from": {"display": "Открыт"}, "to": {"display": "В работе"}},
        {"name": "Исполнитель", "from": None, "to": {"login": "u", "display": "User"}},
    ]
    out = normalize_changelog(fields)
    assert out[0] == {"field": "Статус", "from": "Открыт", "to": "В работе"}
    assert out[1]["from"] == ""
    assert out[1]["to"] == "User"


def test_normalize_changelog_empty():
    assert normalize_changelog(None) == []
    assert normalize_changelog(["мусор"]) == []  # не-словари пропускаются
    assert normalize_changelog([]) == []
