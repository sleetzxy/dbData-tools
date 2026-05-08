import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from db.connection import create_connection, close_connection
from utils.logger_factory import get_logger

LOGGER_NAME = "importer_incremental"
logger = get_logger(LOGGER_NAME)


def get_data_directory(data_source: str, source_type: str = "folder", archive_password: Optional[str] = None) -> str:
    """
    获取数据目录路径，仅支持文件夹数据源
    """
    if not os.path.isdir(data_source):
        raise FileNotFoundError(f"数据目录不存在: {data_source}")
    return data_source

def get_table_names_from_csv(data_dir: str) -> List[str]:
    try:
        return [os.path.splitext(f)[0] for f in os.listdir(data_dir) if f.endswith('.csv')]
    except UnicodeDecodeError:
        tables = []
        for f in os.listdir(data_dir):
            try:
                if f.endswith('.csv'):
                    tables.append(os.path.splitext(f)[0])
            except UnicodeDecodeError:
                try:
                    encoded_f = f.encode('latin-1').decode('gbk')
                    if encoded_f.endswith('.csv'):
                        tables.append(os.path.splitext(encoded_f)[0])
                except:
                    continue
        return tables

def get_table_counts_for_specific_types(conn, schema: str, table: str, type_col: str, values: List[Any], datatype: str = "string") -> int:
    """
    获取表中指定类型列特定值的记录数
    """
    try:
        with conn.cursor() as cursor:
            # 根据数据类型格式化值
            formatted_values = []
            for value in values:
                if datatype in ["string", "text", "varchar"]:
                    formatted_values.append(f"'{value}'")
                else:
                    formatted_values.append(str(value))
            
            values_list = ",".join(formatted_values)
            count_sql = f'SELECT COUNT(1) FROM "{schema}"."{table}" WHERE "{type_col}" IN ({values_list})'
            
            logger.debug(f"统计SQL: {count_sql}")
            cursor.execute(count_sql)
            res = cursor.fetchone()
            return res[0] if res else 0
    except Exception as e:
        logger.error(f"获取表 {schema}.{table} 指定类型记录数时出错: {e}")
        return 0

def format_values_for_sql(values: List[Any], datatype: str = "string") -> List[str]:
    """
    根据数据类型格式化值用于SQL语句
    """
    formatted_values = []
    for value in values:
        if datatype in ["string", "text", "varchar", "char", "date", "timestamp"]:
            # 字符串类型需要加单引号，并转义已有的单引号
            escaped_value = str(value).replace("'", "''")
            formatted_values.append(f"'{escaped_value}'")
        else:
            # 数字类型直接使用
            formatted_values.append(str(value))
    return formatted_values

def generate_delete_sql(schema: str, table: str, type_col: str, values: List[Any], datatype: str = "string") -> str:
    """
    生成DELETE SQL语句，根据数据类型正确处理值
    """
    formatted_values = format_values_for_sql(values, datatype)
    values_list = ",".join(formatted_values)
    delete_sql = f'DELETE FROM "{schema}"."{table}" WHERE "{type_col}" IN ({values_list})'
    return delete_sql

def backup_tables(conn, schema: str, table_names: List[str], backup_dir: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = os.path.join(backup_dir, timestamp)
    os.makedirs(backup_path, exist_ok=True)
    logger.info(f"开始备份表数据到目录: {backup_path}")
    with conn.cursor() as cursor:
        for table in table_names:
            backup_file = os.path.join(backup_path, f"{table}.csv")
            try:
                with open(backup_file, 'w', encoding='utf-8') as f:
                    cursor.copy_expert(
                        f"COPY (SELECT * FROM \"{schema}\".\"{table}\") TO STDOUT WITH (FORMAT CSV, HEADER true, DELIMITER ',', ENCODING 'UTF8')",
                        f
                    )
                logger.info(f"表 {table} 备份成功 -> {backup_file}")
            except Exception as e:
                logger.error(f"表 {table} 备份失败: {e}")
    return backup_path

def generate_copy_commands(table_names: List[str], data_dir: str) -> List[tuple[str, str]]:
    copy_commands: List[tuple[str, str]] = []
    for table in table_names:
        candidates: List[tuple[str, str]] = []
        path = os.path.join(data_dir, f"{table}.csv")
        if os.path.exists(path):
            candidates.append((table, path))
        else:
            try:
                encoded_table = table.encode('gbk').decode('latin-1')
                path_gbk = os.path.join(data_dir, f"{encoded_table}.csv")
                if os.path.exists(path_gbk):
                    candidates.append((table, path_gbk))
            except:
                pass
            try:
                encoded_table = table.encode('utf-8').decode('latin-1')
                path_utf8 = os.path.join(data_dir, f"{encoded_table}.csv")
                if os.path.exists(path_utf8):
                    candidates.append((table, path_utf8))
            except:
                pass
        if not candidates:
            logger.warning(f"CSV文件不存在，跳过该表: {table}")
            continue
        copy_commands.append(candidates[0])
    if not copy_commands:
        logger.error("没有可执行的COPY命令，请检查数据文件是否存在")
    return copy_commands

    """
    保存指定类型数据的变化统计到Excel
    """
    data = []
    for table, before_count in before_counts.items():
        after_count = after_counts.get(table, 0)
        diff = after_count - before_count
        if diff > 0:
            diff_str = f"增加了 {diff} 条数据"
        elif diff < 0:
            diff_str = f"减少了 {-diff} 条数据"
        else:
            diff_str = "无变化"
        data.append({"表名": table, "导入前数据量": before_count, "导入后数据量": after_count, "差异": diff_str})
    
    df = pd.DataFrame(data)
    df.sort_values("表名", inplace=True)
    excel_file = os.path.join(output_path, "导入后统计结果.xlsx")
    df.to_excel(excel_file, index=False)
    
    # 格式化Excel
    wb = load_workbook(excel_file)
    ws = wb.active
    
    # 设置单元格样式
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = Border(
                left=Side(border_style="thin"),
                right=Side(border_style="thin"),
                top=Side(border_style="thin"),
                bottom=Side(border_style="thin"),
            )
    
    # 调整列宽
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                max_len = max(max_len, len(str(cell.value)))
            except:
                pass
        ws.column_dimensions[col_letter].width = max_len + 4
    
    wb.save(excel_file)
    logger.info(f"导入结果已保存至: {excel_file}")

def import_csv_incremental_segmented_to_db(
    db_config: Dict[str, Any],
    data_source: str,
    type_column_map: Dict[str, Dict[str, Any]],
    source_type: str = "folder",
    schema: str = "public",
    need_backup: bool = False,
    archive_password: Optional[str] = None
) -> Dict[str, Any]:
    """
    导入CSV数据：根据GUI输入的表名、列名、列类型和列值先删除数据，然后使用COPY命令导入。
    本函数完全独立，不引用 importer_csv.py 的任何方法，且仅支持文件夹数据源（不处理ZIP）。
    """
    result = {
        "success": True,
        "imported_tables": [],
        "error_tables": [],
        "backup_path": None,
        "data_directory": None
    }

    try:
        data_dir = get_data_directory(data_source, source_type, archive_password)
        result["data_directory"] = data_dir

        if not os.path.isdir(data_dir):
            result["success"] = False
            result["error"] = f"数据目录不存在: {data_dir}"
            return result

        table_names = get_table_names_from_csv(data_dir)
        if not table_names:
            error_msg = f"在目录 {data_dir} 中没有找到CSV文件"
            logger.error(error_msg)
            result["success"] = False
            result["error"] = error_msg
            return result

        logger.info(f"找到以下表的CSV文件: {', '.join(table_names)}")

        # 校验所有表的类型列、类型值数据类型和类型值是否填写（缺失则禁止导入）
        invalid_tables = []
        for table in table_names:
            config = type_column_map.get(table)
            type_col = (config or {}).get("column")
            datatype = (config or {}).get("datatype")
            values = (config or {}).get("values")
            if not config or not type_col or not datatype or not values:
                invalid_tables.append(table)
        if invalid_tables:
            error_msg = f"以下表缺少类型列/类型值数据类型或类型值配置，禁止导入: {', '.join(invalid_tables)}"
            logger.error(error_msg)
            result["success"] = False
            result["error"] = error_msg
            return result

        conn = create_connection(db_config, logger)
        if not conn:
            result["success"] = False
            result["error"] = "数据库连接失败"
            return result
        conn.autocommit = False

        # 获取导入前指定类型的数据量（汇总打印）
        before_counts = {}
        for table in table_names:
            config = type_column_map.get(table)
            if config:
                type_col = config.get("column")
                values = config.get("values", [])
                datatype = config.get("datatype")
                if type_col and values and datatype:
                    count = get_table_counts_for_specific_types(conn, schema, table, type_col, values, datatype)
                    before_counts[table] = count

        if before_counts:
            logger.info("导入前表记录数（按指定类型）:")
            for table, count in before_counts.items():
                logger.info(f"  {table}: {count}")

        if need_backup:
            backup_dir = os.path.join(data_dir, "backup")
            backup_path = backup_tables(conn, schema, table_names, backup_dir)
            result["backup_path"] = backup_path

        copy_commands = generate_copy_commands(table_names, data_dir)

        for table, csv_file in copy_commands:
            try:
                config = type_column_map.get(table)
                if not config:
                    error_msg = f"表 {table} 没有配置类型列/类型值数据类型或类型值，禁止导入"
                    logger.error(error_msg)
                    result["error_tables"].append({"table": table, "error": "缺少类型配置"})
                    result["success"] = False
                    conn.rollback()
                    close_connection(conn, logger)
                    return result

                type_col = config.get("column")
                datatype = config.get("datatype")
                values = config.get("values", [])

                if not type_col or not datatype or not values:
                    error_msg = f"表 {table} 的类型列/类型值数据类型或类型值未填写，禁止导入"
                    logger.error(error_msg)
                    result["error_tables"].append({"table": table, "error": "类型列/数据类型/类型值未填写"})
                    result["success"] = False
                    conn.rollback()
                    close_connection(conn, logger)
                    return result

                logger.info(f"开始处理表 {schema}.{table}，类型列: {type_col}，数据类型: {datatype}")

                # 先删除指定列的指定值（单次IN删除）
                with conn.cursor() as cursor:
                    # 生成DELETE SQL（根据数据类型正确处理值）
                    delete_sql = generate_delete_sql(schema, table, type_col, values, datatype)
                    
                    # 打印DELETE SQL语句
                    logger.info(f"执行DELETE SQL（单次IN删除）: {delete_sql}")
                    
                    cursor.execute(delete_sql)
                    deleted_count = cursor.rowcount
                    logger.info(f"表 {schema}.{table} 删除 {deleted_count} 条记录")
                
                #logger.info(f"表 {schema}.{table} 已删除类型列 {type_col} 的 {len(values)} 个值对应的记录")
                # COPY导入（指定列名）
                logger.info(f"开始导入表 {schema}.{table} 从文件 {csv_file}")
                with conn.cursor() as cursor:
                    with open(csv_file, 'r', encoding='utf-8') as f:
                        header_line = f.readline().strip()
                        if not header_line:
                            raise ValueError(f"CSV文件缺少表头: {csv_file}")
                        columns = [col.strip() for col in header_line.split(',')]
                        column_list = ','.join([f'"{col}"' for col in columns])
                        f.seek(0)
                        copy_sql = f"""
                            COPY "{schema}"."{table}" ({column_list})
                            FROM STDOUT
                            WITH (
                                DELIMITER ',',
                                FORMAT CSV,
                                HEADER true,
                                ENCODING 'UTF8',
                                QUOTE '"',
                                ESCAPE '''' 
                            )
                        """
                        cursor.copy_expert(copy_sql, f)

                result["imported_tables"].append(table)
                logger.info(f"表 {schema}.{table} 导入成功（按指定值删除后导入）")
            except Exception as e:
                error_msg = f"表 {schema}.{table} 导入失败: {str(e)}"
                logger.error(error_msg)
                result["error_tables"].append({"table": table, "error": str(e)})
                result["success"] = False

        if not result["success"]:
            logger.warning("导入过程中发生错误，正在回滚事务")
            conn.rollback()
        else:
            conn.commit()
            logger.info("所有导入操作已成功完成并提交")

            # 获取导入后指定类型的数据量（汇总打印）
            after_counts = {}
            for table in result["imported_tables"]:
                config = type_column_map.get(table)
                if config:
                    type_col = config.get("column")
                    values = config.get("values", [])
                    datatype = config.get("datatype")
                    if type_col and values and datatype:
                        count = get_table_counts_for_specific_types(conn, schema, table, type_col, values, datatype)
                        after_counts[table] = count

            if after_counts:
                logger.info("导入后表记录数（按指定类型）:")
                for table, count in after_counts.items():
                    before_count = before_counts.get(table, 0)
                    diff = count - before_count
                    if diff > 0:
                        change_str = f"增加了 {diff} 条记录"
                    elif diff < 0:
                        change_str = f"减少了 {-diff} 条记录"
                    else:
                        change_str = "无变化"
                    logger.info(f"  {table}: {count}（{change_str}）")


        close_connection(conn, logger)

    except Exception as e:
        error_msg = f"导入（按指定值删除后导入）过程中发生错误: {str(e)}"
        logger.error(error_msg)
        result["success"] = False
        result["error"] = error_msg

    return result