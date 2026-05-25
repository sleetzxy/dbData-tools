from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class TransferMode(Enum):
    """数据传输模式枚举。"""

    CSV = "csv"
    STREAM = "stream"


class SplitMode(Enum):
    """分块拆分模式枚举。"""

    CALENDAR = "calendar"
    PARTITION_VALUE = "partition_value"
    PHYSICAL_PARTITION = "physical"
    KEY_RANGE = "key_range"


class BindType(Enum):
    """分块条件绑定方式枚举。"""

    COLUMN = "column"
    EXPRESSION = "expression"
    NAME_TEMPLATE = "name_template"
    METADATA_LIST = "metadata_list"


@dataclass
class SplitConfig:
    """分块拆分策略配置。"""

    mode: SplitMode = SplitMode.PARTITION_VALUE
    range_start: str = ""
    range_end: str = ""
    value_format: Literal["yyyy-MM-dd", "yyyyMMdd", "yyyyMM", "yyyy"] = "yyyyMMdd"
    granularity: Literal["day", "month", "year"] = "day"
    bind_type: BindType = BindType.COLUMN
    bind_target: str = ""
    batch_size: int = 1
    extra_where: str = ""


@dataclass
class MemoryBudgetConfig:
    """流式迁移内存预算与批量行数约束。"""

    limit_mb: int = 512
    sample_rows: int = 100
    min_batch_rows: int = 100
    max_batch_rows: int = 100_000


@dataclass
class MigrationCondition:
    """单个表的迁移条件与分块配置。"""

    table_name: str
    mode: Literal["where", "sql"]
    # 空字符串表示目标表名与源表相同
    target_table: str = ""
    where_clause: str = ""
    custom_sql: str = ""
    chunk_key: str = ""
    chunk_size: int = 100_000
    enabled: bool = True
    split: SplitConfig = field(default_factory=SplitConfig)


@dataclass
class ChunkSpec:
    """单个分块的键值范围描述。"""

    chunk_index: int
    label: str = ""
    where_sql: str = ""
    physical_targets: list[str] = field(default_factory=list)
    key_start: Any = None
    key_end: Any = None


@dataclass
class TableMigrationResult:
    """单张表的迁移结果。"""

    table_name: str
    success: bool
    total_rows: int
    total_chunks: int
    completed_chunks: int
    error: str = ""


@dataclass
class ChunkProgress:
    """单个分块的迁移进度。"""

    table_name: str
    chunk_index: int
    total_table_chunks: int
    total_across_all_tables: int
    completed_across_all_tables: int
    rows: int


@dataclass
class MigrationMeta:
    """一次迁移任务的元信息与断点状态。"""

    migration_id: str
    tables: list[MigrationCondition]
    completed_chunks: dict[str, set[int]] = field(default_factory=dict)
    created_at: str = ""
