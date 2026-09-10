"""本机凭据混淆加解密工具。"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

_ENV_KEY_FILE = "DBDATA_SECRET_KEY_FILE"
_DEFAULT_KEY_DIR = Path.home() / ".dbdata_tools"
_DEFAULT_KEY_FILE = _DEFAULT_KEY_DIR / ".secret_key"
_TOKEN_PREFIX = "enc:v1:"
_KEY_SIZE = 32


def _get_key_file_path() -> Path:
    """返回密钥文件路径，优先读取环境变量覆盖。"""
    override = os.environ.get(_ENV_KEY_FILE)
    if override:
        return Path(override)
    return _DEFAULT_KEY_FILE


def _ensure_key(key_file: Path) -> bytes:
    """读取或首次生成 32 字节密钥并写入磁盘。"""
    if key_file.exists():
        key = key_file.read_bytes()
        if len(key) != _KEY_SIZE:
            raise ValueError(f"密钥文件长度无效: {key_file}")
        return key

    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(_KEY_SIZE)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(key_file, flags, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


def _get_key() -> bytes:
    """获取当前会话使用的对称密钥。"""
    return _ensure_key(_get_key_file_path())


def _keystream(key: bytes, length: int) -> bytes:
    """基于 hashlib 生成与明文等长的 XOR  keystream。"""
    stream = b""
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        stream += block
        counter += 1
    return stream[:length]


def encrypt_secret(plaintext: str) -> str:
    """将明文凭据加密为带版本前缀的 token，禁止明文落盘。

    :param plaintext: 待加密的明文凭据。
    :return: 形如 ``enc:v1:...`` 的加密 token。
    """
    key = _get_key()
    data = plaintext.encode("utf-8")
    encrypted = bytes(a ^ b for a, b in zip(data, _keystream(key, len(data))))
    encoded = base64.urlsafe_b64encode(encrypted).decode("ascii")
    return f"{_TOKEN_PREFIX}{encoded}"


def decrypt_secret(token: str) -> str:
    """将 ``encrypt_secret`` 生成的 token 解密还原为明文。

    :param token: 加密 token 字符串。
    :return: 解密后的明文凭据。
    :raises ValueError: token 格式无效时抛出。
    """
    if not token.startswith(_TOKEN_PREFIX):
        raise ValueError("无效的加密 token 格式")
    encoded = token[len(_TOKEN_PREFIX) :]
    encrypted = base64.urlsafe_b64decode(encoded.encode("ascii"))
    key = _get_key()
    data = bytes(a ^ b for a, b in zip(encrypted, _keystream(key, len(encrypted))))
    return data.decode("utf-8")
