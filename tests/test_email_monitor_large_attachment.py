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
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"PK\x03\x04data"
    mock_resp.headers = {
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="长春.csv.zip"',
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

    file_resp = MagicMock()
    file_resp.read.return_value = b"PK\x03\x04ZIP"
    file_resp.headers = {
        "Content-Type": "application/zip",
        "Content-Disposition": "",
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
        "core.email_monitor.large_attachment.download_http_file",
        return_value=("file.zip", b"ZIPDATA"),
    ) as mocked:
        results = list(iter_large_attachments_from_message(msg))
    assert results == [("file.zip", b"ZIPDATA")]
    mocked.assert_called_once()
    assert mocked.call_args.kwargs.get("hint_name") == "file.zip"
