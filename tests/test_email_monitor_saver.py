from pathlib import Path

from core.email_monitor.saver import save_attachment_bytes


def test_save_creates_file(tmp_path: Path):
    path = save_attachment_bytes(tmp_path, "a.csv", b"hello")
    assert path == tmp_path / "a.csv"
    assert path.read_bytes() == b"hello"


def test_save_renames_on_collision(tmp_path: Path):
    (tmp_path / "a.csv").write_bytes(b"old")
    path = save_attachment_bytes(tmp_path, "a.csv", b"new")
    assert path == tmp_path / "a_1.csv"
    assert path.read_bytes() == b"new"
    assert (tmp_path / "a.csv").read_bytes() == b"old"
