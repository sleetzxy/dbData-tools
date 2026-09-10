from utils.credential_crypto import decrypt_secret, encrypt_secret


def test_roundtrip_preserves_plaintext(tmp_path, monkeypatch):
    key_file = tmp_path / ".secret_key"
    monkeypatch.setenv("DBDATA_SECRET_KEY_FILE", str(key_file))
    token = encrypt_secret("my-auth-code")
    assert token != "my-auth-code"
    assert not token.startswith("my-auth")
    assert decrypt_secret(token) == "my-auth-code"


def test_empty_string_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DBDATA_SECRET_KEY_FILE", str(tmp_path / "k"))
    assert decrypt_secret(encrypt_secret("")) == ""
