"""超大附件链接提取与下载测试。"""

from __future__ import annotations

import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from core.email_monitor.large_attachment import (
    collect_message_text,
    download_http_file,
    extract_ftn_download_links,
    extract_ftn_links_with_names,
    iter_large_attachments_from_message,
    resolve_tencent_ftn_file,
)


def test_extract_ftn_links_from_html() -> None:
    body = """
    <html><body>
    <a href="https://mail.qq.com/cgi-bin/ftnExs_download?k=abc123&amp;t=exs_ftn_download&amp;code=42eabcbc">
    长春交通大脑20260910版本csv.zip
    </a>
    </body></html>
    """
    links = extract_ftn_download_links(body)
    assert len(links) == 1
    assert "ftnExs_download" in links[0]
    assert "k=abc123" in links[0]
    assert "code=42eabcbc" in links[0]


def test_extract_ftn_links_with_anchor_name() -> None:
    body = (
        '<a href="https://mail.qq.com/cgi-bin/ftnExs_download'
        '?k=abc&amp;code=def">报告.zip</a>'
    )
    pairs = extract_ftn_links_with_names(body)
    assert pairs == [
        (
            "https://mail.qq.com/cgi-bin/ftnExs_download?k=abc&code=def",
            "报告.zip",
        )
    ]


def test_extract_ftn_links_dedup() -> None:
    url = "https://gzc-dfsdown.mail.ftn.qq.com/path/file?ukey=xyz"
    body = f"{url} text {url}"
    assert extract_ftn_download_links(body) == [url]


def test_collect_message_text_includes_html() -> None:
    msg = MIMEMultipart()
    msg.attach(MIMEText("plain body", "plain", "utf-8"))
    msg.attach(
        MIMEText(
            '<a href="https://mail.qq.com/cgi-bin/ftnExs_download?k=1&code=2">f</a>',
            "html",
            "utf-8",
        )
    )
    text = collect_message_text(msg)
    assert "plain body" in text
    assert "ftnExs_download" in text


def test_download_direct_file_uses_content_disposition() -> None:
    payload = b"PK\x03\x04data"
    mock_resp = MagicMock()
    mock_resp.read.side_effect = _chunked_read_side_effect(payload)
    mock_resp.headers = {
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="长春.csv.zip"',
        "Content-Length": str(len(payload)),
    }
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch(
        "core.email_monitor.large_attachment.urlopen", return_value=mock_resp
    ):
        name, data = download_http_file(
            "https://gzc-dfsdown.mail.ftn.qq.com/x?fname=a.zip"
        )
    assert name == "长春.csv.zip"
    assert data.startswith(b"PK")


def _chunked_read_side_effect(payload: bytes, chunk_size: int = 4):
    """模拟 HTTP 响应分块 read，读完返回空。"""
    offset = {"n": 0}

    def _read(size: int = -1) -> bytes:
        start = offset["n"]
        if start >= len(payload):
            return b""
        if size is None or size < 0:
            offset["n"] = len(payload)
            return payload[start:]
        end = min(start + size, len(payload))
        offset["n"] = end
        return payload[start:end]

    return _read


def test_resolve_tencent_ftn_file_preserves_cookie() -> None:
    meta = {
        "head": {"ret": 0},
        "body": {
            "name": "长春.csv.zip",
            "url": "https://wx.mail.qq.com/ftn/download?func=4&key=K&code=C",
            "size": 10,
        },
    }
    meta_resp = MagicMock()
    meta_resp.read.return_value = json.dumps(meta).encode("utf-8")
    meta_resp.__enter__.return_value = meta_resp
    meta_resp.__exit__.return_value = False

    redirect_headers = MagicMock()
    redirect_headers.get.side_effect = lambda k, default=None: {
        "Location": "https://gzc-dfsdown.mail.ftn.qq.com/file?fname=x.zip",
        "Set-Cookie": "mail5k=abc",
    }.get(k, default)
    redirect_headers.get_all.return_value = ["mail5k=abc; Path=/"]

    payload = b"PK\x03\x04ZIP"
    file_resp = MagicMock()
    file_resp.read.side_effect = _chunked_read_side_effect(payload)
    file_resp.headers = {
        "Content-Type": "application/zip",
        "Content-Disposition": "",
        "Content-Length": str(len(payload)),
    }
    file_resp.__enter__.return_value = file_resp
    file_resp.__exit__.return_value = False

    opener = MagicMock()
    # 1) meta OK  2) func4 → HTTPError 302  3) dfsdown OK
    opener.open.side_effect = [
        meta_resp,
        HTTPError(
            "https://wx.mail.qq.com/ftn/download?func=4",
            302,
            "Found",
            hdrs=redirect_headers,
            fp=None,
        ),
        file_resp,
    ]

    with patch(
        "core.email_monitor.large_attachment.build_opener",
        return_value=opener,
    ):
        name, data = resolve_tencent_ftn_file(
            "https://mail.qq.com/cgi-bin/ftnExs_download?k=K&code=C"
        )

    assert name == "长春.csv.zip"
    assert data == b"PK\x03\x04ZIP"
    # 第三次请求应带 Cookie
    third_req = opener.open.call_args_list[2].args[0]
    assert third_req.get_header("Cookie") == "mail5k=abc"


def test_read_response_bytes_reports_progress(caplog) -> None:
    """已知总大小时按百分比输出下载进度（debug），并回调 on_progress。"""
    import logging

    from core.email_monitor.large_attachment import read_response_bytes

    total = 1000
    payload = b"x" * total
    resp = MagicMock()
    resp.read.side_effect = _chunked_read_side_effect(payload, chunk_size=100)
    callbacks: list[tuple[str, int, int | None, bool]] = []

    with caplog.at_level(logging.DEBUG, logger="core.email_monitor.large_attachment"):
        data = read_response_bytes(
            resp,
            label="demo.zip",
            total_size=total,
            chunk_size=100,
            on_progress=lambda name, done_n, total_n, finished: callbacks.append(
                (name, done_n, total_n, finished)
            ),
        )

    assert data == payload
    assert callbacks, "应回调 on_progress"
    assert callbacks[0][0] == "demo.zip"
    assert callbacks[0][3] is False
    assert callbacks[-1][3] is True
    assert callbacks[-1][1] == total
    assert any(c[1] > 0 and not c[3] for c in callbacks)


def test_iter_large_attachments_from_message_downloads() -> None:
    msg = MIMEMultipart()
    msg["From"] = "xiehaiying@pcitech.com"
    msg["Subject"] = "=?utf-8?B?5rWL6K+V?="
    msg.attach(
        MIMEText(
            '<a href="https://mail.qq.com/cgi-bin/ftnExs_download?k=aa&code=bb">'
            "file.zip</a>",
            "html",
            "utf-8",
        )
    )

    with patch(
        "core.email_monitor.large_attachment.resolve_tencent_ftn_meta",
        return_value=("file.zip", "https://dfs/file", "mail5k=x", 7),
    ), patch(
        "core.email_monitor.large_attachment.download_tencent_ftn_bytes",
        return_value=b"ZIPDATA",
    ) as mocked:
        results = list(iter_large_attachments_from_message(msg))
    assert results == [("file.zip", b"ZIPDATA")]
    mocked.assert_called_once()


def test_iter_large_attachments_skips_download_when_should_skip() -> None:
    """去重命中时只解析元数据拿文件名，不下载正文。"""
    msg = MIMEMultipart()
    msg["Subject"] = "已处理过的超大附件"
    msg.attach(
        MIMEText(
            '<a href="https://mail.qq.com/cgi-bin/ftnExs_download?k=aa&code=bb">'
            "seen.zip</a>",
            "html",
            "utf-8",
        )
    )

    with (
        patch(
            "core.email_monitor.large_attachment.resolve_tencent_ftn_meta",
            return_value=("seen.zip", "https://dfs/file", "mail5k=x", 10),
        ) as meta_mock,
        patch(
            "core.email_monitor.large_attachment.download_tencent_ftn_bytes",
        ) as dl_mock,
        patch(
            "core.email_monitor.large_attachment.download_http_file",
        ) as http_mock,
    ):
        results = list(
            iter_large_attachments_from_message(
                msg,
                should_skip=lambda name: name == "seen.zip",
            )
        )

    assert results == []
    meta_mock.assert_called_once()
    dl_mock.assert_not_called()
    http_mock.assert_not_called()


def test_direct_link_discards_when_final_name_already_deduped() -> None:
    """直链预判名未去重，但最终 Content-Disposition 名已去重时应丢弃。"""
    msg = MIMEMultipart()
    msg.attach(
        MIMEText(
            '<a href="https://gzc-dfsdown.mail.ftn.qq.com/x?fname=hint.zip">'
            "hint.zip</a>",
            "html",
            "utf-8",
        )
    )
    with patch(
        "core.email_monitor.large_attachment.download_http_file",
        return_value=("final.zip", b"DATA"),
    ) as dl_mock:
        results = list(
            iter_large_attachments_from_message(
                msg,
                should_skip=lambda name: name == "final.zip",
            )
        )
    assert results == []
    dl_mock.assert_called_once()
