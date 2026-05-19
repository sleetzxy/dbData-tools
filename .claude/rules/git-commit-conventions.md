---
description: Git 提交说明（Angular 约定式提交）+ AI 辅助与合著者标注
---

# Git Commit 规范

## 提交粒度

一次提交只处理一个主题，避免无关修改混在同一 commit。

## 结构

```
<type>(<scope>): <subject>

<body>

<footer>
```

- **Header** 必填；**Body**、**Footer** 按需。
- 单行不超过 72 字符。

## Header

- **type**（必选）：`feat` | `fix` | `docs` | `style` | `refactor` | `test` | `chore`
- **scope**（可选）：`gui`、`core`、`db`、具体模块名
- **subject**（必选）：≤50 字符，动词开头、现在时、首字母小写、句末不加句号

本仓库采用「英文 type + 中文描述」：

```
fix(csv): 解决 CSV 导出编码异常
refactor: 调整连接配置校验提示
docs: 重写仓库协作说明
```

## Body

说明动机、与之前行为的对比。可分段、可用列表。语态与 subject 一致（现在时）。

## Footer

- **破坏性变更**：`BREAKING CHANGE:` 开头，说明变更与迁移方式
- **关联 Issue**：`Closes #123`
- **撤销提交**：Header 以 `revert:` 开头；Body 固定含 `This reverts commit <hash>.`

## AI 辅助提交

当 AI 参与起草、重构或生成代码时，在 Footer 标注：

```
AI-Assisted-by: Claude Code
Co-authored-by: 提交人姓名 <email>  <!-- 真实提交人，非 AI -->
```

若 AI 仅参与 commit message 润色，未参与代码：Body 末行写 `AI used only for commit message wording.`

## 提交前检查

- 确认未误带 `build/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`*.egg-info/`
- 合并到主干前，先确保当前分支验证通过
