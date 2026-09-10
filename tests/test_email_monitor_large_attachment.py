"""超大附件链接提取与下载测试。"""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

from core.email_monitor.large_attachment import (
    collect_message_text,
    download_http_file,
    extract_ftn_download_links,
    iter_large_attachments_from_message,
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


def test_download_http_file_uses_content_disposition() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"PK\x03\x04data"
    mock_resp.headers = {
        "Content-Disposition": 'attachment; filename="长春.csv.zip"'
    }
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch(
        "core.email_monitor.large_attachment.urlopen", return_value=mock_resp
    ):
        name, data = download_http_file(
            "https://mail.qq.com/cgi-bin/ftnExs_download?k=1&code=2"
        )
    assert name == "长春.csv.zip"
    assert data.startswith(b"PK")


def test_iter_large_attachments_from_message_downloads() -> None:
    msg = MIMEMultipart()
    msg["From"] = "xiehaiying@pcitech.com"
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
