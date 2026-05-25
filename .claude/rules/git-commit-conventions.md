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

### 获取提交人身份（生成 Co-authored-by 前必做）

**禁止**使用占位符（如 `提交人姓名`、`<email>`、示例邮箱）。生成 commit message 前，**必须先执行**：

```bash
git config user.name
git config user.email
```

- 将上述命令的**实际输出**填入 `Co-authored-by: <name> <email>`（格式：`姓名 <邮箱>`）。
- 上述命令无输出时，再依次尝试 `git config --global user.name` / `git config --global user.email`。
- 若仍无法取得有效姓名或邮箱，**暂停提交**并向用户确认，不得臆造或沿用文档示例值。

### 示例

```
feat(auth): add jwt refresh token flow

- Refactor session handling for clearer token lifecycle.
- AI drafted initial refresh flow; human reviewed edge cases.

AI-Assisted-by: Claude Code
Co-authored-by: Zhang San <zhangsan@company.com>
```

上例中 `Co-authored-by` 的姓名与邮箱须替换为 `git config` 的实际输出，**不得**照抄示例。

### 约定

- **AI-Assisted-by**：使用的工具或模型产品线名称。
- **Co-authored-by**：符合 [Git trailer 格式](https://git-scm.com/docs/git-interpret-trailers)；**每行一人**。**必须**包含本次 Git 提交人（与 `git config user.name` / `user.email` 一致，通常即 Author）；另有真实合著者可追加多行。

若 AI **仅**参与 commit message 润色、**未**参与代码：Body 末行写 `AI used only for commit message wording.`

## 提交前检查

- 确认未误带 `build/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`*.egg-info/`
- 合并到主干前，先确保当前分支验证通过
