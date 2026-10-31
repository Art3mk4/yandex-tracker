"""link_next_params: курсорная пагинация из заголовка Link."""
from app.tracker_sync import link_next_params

HEADER = (
    '<https://api.tracker.yandex.net/v3/issues/KEY/comments?expand=&perPage=100>; rel="first", '
    '<https://api.tracker.yandex.net/v3/issues/KEY/comments?expand=&id=1009&perPage=100>; rel="next"'
)


def test_next_cursor_extracted():
    assert link_next_params(HEADER) == {"id": "1009", "perPage": "100"}


def test_no_next_returns_none():
    assert link_next_params('<https://x/y?perPage=1>; rel="first"') is None
    assert link_next_params("") is None


def test_empty_params_dropped():
    header = '<https://x/y?expand=&field=&id=abc>; rel="next"'
    assert link_next_params(header) == {"id": "abc"}
