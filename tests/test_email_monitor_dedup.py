from core.email_monitor.dedup import DedupStore, make_dedup_key


def test_make_dedup_key_includes_account():
    assert make_dedup_key("u@x.com", "123", "a.csv") == "u@x.com|123|a.csv"


def test_dedup_store_persists(tmp_path):
    store = DedupStore(tmp_path / "seen.json")
    key = make_dedup_key("u@x.com", "1", "a.csv")
    assert not store.has(key)
    store.add(key)
    assert store.has(key)
    store2 = DedupStore(tmp_path / "seen.json")
    assert store2.has(key)
