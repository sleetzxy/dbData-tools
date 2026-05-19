---
paths:
  - "**/*.py"
  - "*.py"
description: Python 编码规范（PEP 8、类型标注、命名、常见模式）
---

# Python 编码规范

## 格式

- 缩进 4 空格，不用 Tab。行宽 88 字符（ruff 配置）。文档字符串/注释尽量 72 字符内换行。
- 空行：顶层函数/类之间两行，类内方法之间一行，函数内逻辑分段一行。
- 使用 ruff 自动格式化（line-length=88，double-quote），提交前确保通过。

## Import 顺序

1. 标准库
2. 第三方库
3. 本地项目导入（`from core...`、`from db...`、`from gui...`、`from utils...`，不要写 `from src.core...`）

各组内按字母序排列，优先使用绝对导入。

## 命名

| 类型 | 风格 | 示例 |
|------|------|------|
| 模块/包 | `lowercase_with_underscores` | `csv_handler.py` |
| 类 | `CamelCase` | `MainApplication` |
| 函数/方法 | `lowercase_with_underscores` | `get_user_by_id()` |
| 变量 | `lowercase_with_underscores` | `user_count` |
| 常量 | `UPPERCASE_WITH_UNDERSCORES` | `MAX_RETRY` |
| 保护成员 | `_leading_underscore` | `_internal_method()` |
| 私有成员 | `__double_leading_underscore` | 尽量少用 |

## 类型标注

所有函数签名必须标注参数和返回值类型。复杂类型使用 `typing` 模块（`List`、`Dict`、`Optional`、`Union`、`TypeAlias` 等）。

## 文档字符串与注释

公共模块、类、函数使用 PEP 257 reStructuredText 风格文档字符串（`:param`、`:return`、`:raises`）。
注释解释「为什么这样做」（业务上下文、规避的坑），不重复代码字面含义。

## 常见模式与反模式

**上下文管理器** — 文件操作必须用 `with`：

```python
with open("file.txt", "r") as f:
    data = f.read()
```

**f-string** — 优先 f-string 格式化，但避免内联复杂表达式：

```python
print(f"Hello, {name}. You are {age} years old.")
```

**Enum** — 符号常量用 `enum.Enum`：

```python
class Status(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
```

**可变默认参数** — 禁止，用 `None` + 内部初始化：

```python
def add_item(item: Any, item_list: list[Any] | None = None) -> list[Any]:
    if item_list is None:
        item_list = []
    item_list.append(item)
    return item_list
```

**异常捕获** — 捕获具体异常类型，禁止裸 `except:`：

```python
try:
    result = 1 / 0
except ZeroDivisionError:
    print("Cannot divide by zero.")
```

**列表推导** — 优先于显式循环（除非逻辑复杂影响可读性）。
