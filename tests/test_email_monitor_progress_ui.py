"""邮件监控页进度日志行为测试。"""

from __future__ import annotations

import customtkinter as ctk

from gui.pages.email.monitor import EmailMonitorPage


def test_progress_queue_keeps_finished_when_next_file_starts() -> None:
    """A 完成后再入队 B 时，flush 后 A 应为「下载完成」且保留独立行。"""
    root = ctk.CTk()
    root.withdraw()
    try:
        page = EmailMonitorPage(root)
        # 直接入队，避免 after 异步干扰断言
        page._progress_queue.append(("a.zip", 50, 100, False))
        page._progress_queue.append(("a.zip", 100, 100, True))
        page._progress_queue.append(("b.zip", 10, 100, False))
        page._flush_download_progress()

        content = page.text_log.get("1.0", "end")
        assert "下载完成：a.zip" in content
        assert "正在下载：b.zip" in content
        assert content.index("a.zip") < content.index("b.zip")
    finally:
        root.destroy()


def test_same_filename_starts_new_line_after_finish() -> None:
    """同名文件在上一份结束后应新起一行，不覆盖旧「下载完成」。"""
    root = ctk.CTk()
    root.withdraw()
    try:
        page = EmailMonitorPage(root)
        page._apply_download_progress("same.zip", 10, 10, True)
        first = page.text_log.get("1.0", "end")
        assert "下载完成：same.zip" in first

        page._apply_download_progress("same.zip", 1, 10, False)
        content = page.text_log.get("1.0", "end")
        assert content.count("same.zip") == 2
        assert "正在下载：same.zip" in content
        assert "下载完成：same.zip" in content
    finally:
        root.destroy()


def test_attachment_saved_rewrites_progress_line() -> None:
    """落盘回调把「下载完成」改成「已保存」。"""
    root = ctk.CTk()
    root.withdraw()
    try:
        page = EmailMonitorPage(root)
        page._apply_download_progress("a.zip", 10, 10, True)
        page._apply_attachment_saved("a.zip", 10)
        content = page.text_log.get("1.0", "end")
        assert "已保存：a.zip" in content
        assert "下载完成：a.zip" not in content
    finally:
        root.destroy()
