---
paths:
  - "tests/**/*.py"
  - "**/test_*.py"
  - "**/conftest.py"
  - "*.py"
description: pytest 测试规范（布局、fixture、mock、参数化、覆盖率）
---

# pytest 测试规范

pytest 配置见 `pyproject.toml`：`testpaths = ["tests"]`，`pythonpath = ["src"]`，`addopts = "-q"`。

## 布局与命名

使用 `src/` 布局，测试放在 `tests/` 目录。`tests/` 含 `__init__.py` 使其成为包。

- 测试文件：`test_<module>.py`
- 测试函数：`test_<descriptive_name>`，名称应能阅读成句（如 `test_user_can_be_created_with_valid_email`）
- 测试类：`Test<Name>`（前缀 Test，不是后缀如 `UserServiceTest`）

## Fixture

- 用 `pytest.fixture` 管理 setup/teardown，`yield` 实现 teardown
- scope：`function`（默认，绝大多数场景）、`class`、`module`、`session`（仅全局昂贵资源如 DB 连接池）
- 通过注入组合 fixture（fixture 可依赖其他 fixture）
- 避免 `autouse=True`，除非真正全局无副作用的设置（如全局 patch）
- 禁止 unittest 风格的 `setup_method` / `teardown_method`

## 参数化

```python
@pytest.mark.parametrize("input_val, expected", [
    (1, 2),
    (2, 3),
    (0, 1),
])
def test_increment(input_val, expected):
    assert increment(input_val) == expected
```

## Mock

优先用 `mocker` fixture（pytest-mock），不直接使用 `monkeypatch.setattr` 做复杂 mock。

```python
def test_service_fetches_data(mocker):
    mock_get = mocker.patch("mypackage.service.get_data")
    mock_get.return_value = {"key": "mocked"}
    # ...
    mock_get.assert_called_once()
```

## 覆盖率

```bash
pytest --cov=core --cov=db --cov=gui --cov=utils --cov-report=term-missing
```

## 原则

- 每个测试只验证一个行为（单一 assert 倾向）
- Mock 外部服务保持测试快速
- 测试代码也加类型标注
- `@pytest.mark.skip(reason="...")` / `@pytest.mark.xfail(reason="...")` 标明已知问题
- 改动涉及导入导出、数据库更新或迁移时，必须补充异常分支和空数据场景的验证
