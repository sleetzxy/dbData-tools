import os
import zipfile
from typing import List, Dict, Any, Tuple, Optional

import pyzipper

from db.connection import create_connection, close_connection
from utils.logger_factory import get_logger

LOGGER_NAME = "importer"
logger = get_logger(LOGGER_NAME)


def extract_zip_file_unified(zip_path: str, password: Optional[str] = None) -> str:
    """解压 ZIP 文件，同时兼容 AES 加密与常见文件名编码问题。"""
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(f"ZIP 文件不存在: {zip_path}")
    if not zip_path.lower().endswith('.zip'):
        raise ValueError(f"不是 ZIP 文件: {zip_path}")

    zip_dir = os.path.dirname(zip_path)
    zip_name = os.path.splitext(os.path.basename(zip_path))[0]
    extract_dir = os.path.join(zip_dir, zip_name)

    if os.path.exists(extract_dir):
        logger.info(f"解压目录已存在，直接使用: {extract_dir}")
        return extract_dir
    os.makedirs(extract_dir, exist_ok=True)

    def _sanitize_windows_filename(name: str) -> str:
        invalid_chars = '<>:"\\|?*'
        sanitized = ''.join('_' if c in invalid_chars else c for c in name)
        return sanitized.strip().rstrip('.')

    def _normalize_and_sanitize(path: str) -> str:
        normalized = path.replace('\\', '/')
        parts = [p for p in normalized.split('/') if p not in ('', '.', '..')]
        safe_parts = [_sanitize_windows_filename(p) for p in parts]
        return os.path.join(*safe_parts) if safe_parts else ''

    def _decode_zip_filename(name: str, info) -> str:
        if hasattr(info, 'flag_bits') and (info.flag_bits & 0x800) != 0:
            return _normalize_and_sanitize(name)

        for enc in ['gbk', 'gb2312', 'big5', 'utf-8']:
            try:
                raw = name.encode('cp437')
                decoded = raw.decode(enc)
                return _normalize_and_sanitize(decoded)
            except Exception:
                continue
        return _normalize_and_sanitize(name)

    try:
        with pyzipper.AESZipFile(zip_path) as zf:
            for file_info in zf.infolist():
                original_filename = file_info.filename
                decoded_path = _decode_zip_filename(original_filename, file_info)

                if (hasattr(file_info, 'is_dir') and file_info.is_dir()) or original_filename.endswith('/'):
                    dir_path = os.path.join(extract_dir, decoded_path)
                    if dir_path:
                        os.makedirs(dir_path, exist_ok=True)
                    continue

                target_path = os.path.join(extract_dir, decoded_path)
                parent_dir = os.path.dirname(target_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                try:
                    with zf.open(file_info, pwd=password.encode('utf-8') if password else None) as src, open(target_path, 'wb') as dst:
                        dst.write(src.read())
                except RuntimeError as exc:
                    if 'password' in str(exc).lower():
                        raise ValueError("ZIP 压缩包密码错误或未提供密码")
                    raise
                except Exception as exc:
                    logger.warning(f"解压文件失败 {decoded_path}: {exc}")
                    continue

        logger.info(f"ZIP 解压完成: {zip_path} -> {extract_dir}")
        return extract_dir
    except zipfile.BadZipFile:
        raise ValueError(f"无效的 ZIP 文件: {zip_path}")
    except Exception as exc:
        raise Exception(f"解压 ZIP 文件失败: {exc}")


def get_data_directory(data_source: str, source_type: str = "folder", archive_password: Optional[str] = None) -> str:
    """根据数据源类型返回可用的数据目录。"""
    if source_type == "folder":
        if not os.path.isdir(data_source):
            raise FileNotFoundError(f"数据目录不存在: {data_source}")
        return data_source
    if source_type == "zip":
        return extract_zip_file_unified(data_source, archive_password)
    raise ValueError(f"不支持的数据来源类型: {source_type}")


def get_table_names_from_csv(data_dir: str) -> List[str]:
    """从目录中的 CSV 文件名提取表名。"""
    try:
        table_names = []
        for filename in os.listdir(data_dir):
            if filename.endswith('.csv'):
                table_names.append(os.path.splitext(filename)[0])
        return table_names
    except UnicodeDecodeError:
        try:
            table_names = []
            for filename in os.listdir(data_dir):
                try:
                    if filename.endswith('.csv'):
                        table_names.append(os.path.splitext(filename)[0])
                except UnicodeDecodeError:
                    try:
                        decoded_name = filename.encode('latin-1').decode('gbk')
                        if decoded_name.endswith('.csv'):
                            table_names.append(os.path.splitext(decoded_name)[0])
                    except Exception:
                        continue
            return table_names
        except Exception as exc:
            logger.error(f"读取 CSV 文件列表失败: {exc}")
            return []


def generate_copy_commands(table_names: List[str], data_dir: str) -> List[Tuple[str, str]]:
    """生成 (表名, CSV 路径) 列表。"""
    copy_commands = []
    for table in table_names:
        csv_files = []

        csv_file = os.path.join(data_dir, f'{table}.csv')
        if os.path.exists(csv_file):
            csv_files.append((table, csv_file))
        else:
            try:
                encoded_table = table.encode('gbk').decode('latin-1')
                csv_file_gbk = os.path.join(data_dir, f'{encoded_table}.csv')
                if os.path.exists(csv_file_gbk):
                    csv_files.append((table, csv_file_gbk))
            except Exception:
                pass

            try:
                encoded_table = table.encode('utf-8').decode('latin-1')
                csv_file_utf8 = os.path.join(data_dir, f'{encoded_table}.csv')
                if os.path.exists(csv_file_utf8):
                    csv_files.append((table, csv_file_utf8))
            except Exception:
                pass

        if not csv_files:
            logger.warning(f"未找到表对应的 CSV 文件: {table}")
            continue

        copy_commands.append(csv_files[0])

    if not copy_commands:
        logger.error("未生成任何 COPY 指令，请检查数据文件")
    return copy_commands


def read_sql_from_file(file_path: str) -> str:
    """读取 SQL 文件内容，仅支持 txt 或 sql 扩展名。"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"SQL 文件不存在: {file_path}")
    if not file_path.lower().endswith(('.txt', '.sql')):
        raise ValueError(f"SQL 文件格式不支持: {file_path}，仅支持 txt 或 sql")
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def _normalize_schema(db_type: str, schema: str) -> str:
    schema_value = ""
    if schema is not None:
        schema_value = str(schema).strip()

    if db_type == "postgresql":
        return schema_value or "public"
    if db_type == "clickhouse":
        return ""
    return schema_value if schema is not None else schema


def import_csv_to_db(
    db_config: Dict[str, Any],
    data_source: str,
    source_type: str = "folder",
    schema: str = "public",
    pre_sql_file: str = "",
    need_backup: bool = False,
    archive_password: Optional[str] = None,
) -> Dict[str, Any]:
    """将 CSV 数据导入数据库，支持目录或 ZIP 数据源。"""
    effective_schema = _normalize_schema(db_config.get("db_type"), schema)
    result = {
        "success": True,
        "imported_tables": [],
        "error_tables": [],
        "backup_path": None,
        "data_directory": None,
        "schema": effective_schema,
    }

    try:
        data_dir = get_data_directory(data_source, source_type, archive_password)
        result["data_directory"] = data_dir

        if not os.path.isdir(data_dir):
            result["success"] = False
            result["error"] = f"数据目录无效: {data_dir}"
            return result

        table_names = get_table_names_from_csv(data_dir)
        if not table_names:
            error_msg = f"目录 {data_dir} 中未找到 CSV 文件"
            logger.error(error_msg)
            result["success"] = False
            result["error"] = error_msg
            return result

        logger.info(f"检测到 CSV 表: {', '.join(table_names)}")

        conn = create_connection(db_config, logger)
        if not conn:
            result["success"] = False
            result["error"] = "数据库连接失败"
            return result

        adapter_schema = _normalize_schema(conn.db_type, schema)
        try:
            adapter_result = conn.adapter.import_csv(
                conn.client,
                db_config=db_config,
                table_names=table_names,
                data_dir=data_dir,
                schema=adapter_schema,
                pre_sql_file=pre_sql_file,
                need_backup=need_backup,
                logger=logger,
            )

            if adapter_result is None:
                result["success"] = False
                result["error"] = "导入返回结果为空"
            else:
                result.update(adapter_result)
                if not result.get("data_directory"):
                    result["data_directory"] = data_dir
                result["schema"] = _normalize_schema(
                    db_config.get("db_type"),
                    result.get("schema", effective_schema),
                )
        finally:
            close_connection(conn, logger)

    except Exception as exc:
        error_msg = f"导入过程中发生错误: {exc}"
        logger.error(error_msg)
        result["success"] = False
        result["error"] = error_msg

    return result
