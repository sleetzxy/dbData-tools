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

当 AI 参与起草、重构或生成代码时，在 Footer 标注工具与合著者信息。

### 确定实际代码编写者（生成 Co-authored-by 前必做）

**Co-authored-by** 标注**实际编写本次变更代码**的合著者，**不是**默认填入执行 `git commit` 的 Git 提交人（Author 已由 git 自动记录）。

**禁止**使用占位符（如 `提交人姓名`、`<email>`、示例邮箱）。

- **AI 参与写代码**：必须添加对应工具的 `Co-authored-by`，例如：
  - Cursor：`Co-authored-by: Cursor <cursoragent@cursor.com>`
  - Claude Code：`Co-authored-by: Claude Code <noreply@anthropic.com>`
- **纯人工编写**（AI 仅润色 commit message）：无需 `Co-authored-by`。
- **多人协作写代码**：每行一人，仅列实际写代码者；姓名与邮箱须真实有效，不知晓时向用户确认，不得臆造。

### 示例

```
feat(auth): add jwt refresh token flow

- Refactor session handling for clearer token lifecycle.
- AI drafted initial refresh flow; human reviewed edge cases.

AI-Assisted-by: Claude Code
Co-authored-by: Claude Code <noreply@anthropic.com>
```

上例中 AI 起草代码，`Co-authored-by` 标注实际代码编写者（AI），**不得**照抄为 Git 提交人身份。

### 约定

- **AI-Assisted-by**：使用的工具或模型产品线名称。
- **Co-authored-by**：符合 [Git trailer 格式](https://git-scm.com/docs/git-interpret-trailers)；**每行一人**。**必须**标注**实际编写代码**的主体（AI 或人工合著者），而非 Git 提交人。

若 AI **仅**参与 commit message 润色、**未**参与代码：Body 末行写 `AI used only for commit message wording.`

## 提交前检查

- 确认未误带 `build/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`*.egg-info/`
- 合并到主干前，先确保当前分支验证通过
