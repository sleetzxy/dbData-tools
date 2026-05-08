"""Pytest 共享 fixture 与测试发现配置。

M1 阶段仓库仍为根下扁平包结构。本文件把仓库根加入 sys.path，
让 pytest 在未执行可编辑安装时也能解析 core/db/gui/utils 包。
M2 迁移到 src/ 布局并以可编辑安装运行后，本文件可被精简或删除。
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
