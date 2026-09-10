from core.email_monitor.filters import (
    extension_allowed,
    normalize_extensions,
    parse_sender_list,
    sender_matches,
)


def test_parse_sender_list_comma_and_newline():
    assert parse_sender_list("a@x.com, b@y.com\nc@z.com") == {
        "a@x.com",
        "b@y.com",
        "c@z.com",
    }


def test_sender_matches_ignores_display_name_and_case():
    allowed = {"foo@bar.com"}
    assert sender_matches("Foo Bar <FOO@BAR.COM>", allowed)
    assert not sender_matches("other@bar.com", allowed)


def test_extension_whitelist_required_semantics():
    assert normalize_extensions(".CSV, xlsx") == {".csv", ".xlsx"}
    assert extension_allowed("report.CSV", {".csv"})
    assert not extension_allowed("report.txt", {".csv"})
    assert not extension_allowed("report.csv", set())  # 空白名单不下任何文件
