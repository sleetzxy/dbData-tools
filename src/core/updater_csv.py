import os
import csv
from typing import Dict, Tuple, Any
from db.connection import create_connection, close_connection
from utils.logger_factory import get_logger

LOGGER_NAME = "updater"
logger = get_logger(LOGGER_NAME)

def load_mapping(mapping_file: str, mode: str = 'encrypt') -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """
    加载映射关系（表名和列名）
    
    参数:
        mapping_file: 映射文件路径
        mode: 'encrypt' 或 'decrypt'，决定映射方向
        
    返回:
        表名映射字典和列名映射字典的元组
    """
    logger.info(f"开始加载映射文件: {mapping_file} (模式: {mode})")
    table_mapping = {}
    column_mapping = {}
    total_mappings = 0

    try:
        with open(mapping_file, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 根据模式决定映射方向
                if mode == 'encrypt':
                    original_table = row['original_table_name']
                    new_table = row['meaningless_table_name']
                    original_column = row['original_column_name']
                    new_column = row['meaningless_column_name']
                else:  # decrypt
                    original_table = row['meaningless_table_name']
                    new_table = row['original_table_name']
                    original_column = row['meaningless_column_name']
                    new_column = row['original_column_name']

                # 建立表名映射
                if original_table not in table_mapping:
                    table_mapping[original_table] = new_table

                # 建立列名映射
                if original_table not in column_mapping:
                    column_mapping[original_table] = {}

                column_mapping[original_table][original_column] = new_column
                total_mappings += 1

        logger.info(f"映射文件加载完成，共加载 {len(table_mapping)} 个表映射和 {total_mappings} 个列映射")
        return table_mapping, column_mapping

    except Exception as e:
        logger.error(f"加载映射文件时出错: {str(e)}")
        raise


def process_csv_files(input_folder: str, table_mapping: Dict[str, str],
                      column_mapping: Dict[str, Dict[str, str]], mode: str = 'encrypt') -> Dict[str, Any]:
    """
    处理CSV文件

    参数:
        input_folder: 输入文件夹路径
        table_mapping: 表名映射字典
        column_mapping: 列名映射字典
        mode: 'encrypt' 或 'decrypt'，决定输出文件夹名称和处理方向

    返回:
        处理结果信息的字典
    """
    # 增加字段大小限制到 10MB
    csv.field_size_limit(10 * 1024 * 1024)

    result = {
        "success": True,
        "processed_files": [],
        "copied_files": [],  # 新增：记录原样复制的文件
        "error_files": [],
        "output_folder": ""
    }

    output_folder_name = '加密后' if mode == 'encrypt' else '解密后'
    output_folder = os.path.join(input_folder, output_folder_name)
    result["output_folder"] = output_folder

    logger.info(f"开始处理CSV文件，模式: {mode}, 输入文件夹: {input_folder}, 输出文件夹: {output_folder}")
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        logger.info(f"创建输出文件夹: {output_folder}")

    all_files = [f for f in os.listdir(input_folder) if f.endswith('.csv')]
    logger.info(f"共发现 {len(all_files)} 个CSV文件需要处理")

    for i, filename in enumerate(all_files, 1):
        original_table_name = os.path.splitext(filename)[0]
        logger.info(f"正在处理文件 {i}/{len(all_files)}: {filename}")

        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)  # 默认输出路径

        # 表名有映射
        if original_table_name in table_mapping:
            new_table_name = table_mapping[original_table_name]
            output_path = os.path.join(output_folder, f"{new_table_name}.csv")

            try:
                with open(input_path, mode='r', encoding='utf-8') as infile, \
                        open(output_path, mode='w', encoding='utf-8', newline='') as outfile:

                    # 读取第一行表头
                    header_line = infile.readline()
                    raw_headers = next(csv.reader([header_line]))

                    if original_table_name in column_mapping:
                        column_map = column_mapping[original_table_name]
                        new_headers = [column_map.get(col, col) for col in raw_headers]

                        # 根据 header_line 是否含引号判断是否加引号
                        final_header_line = ",".join(
                            f'"{new}"' if f'"{old}"' in header_line else new
                            for new, old in zip(new_headers, raw_headers)
                        )
                        outfile.write(final_header_line + "\n")

                        # 提示哪些列未映射
                        unmapped_columns = [col for col in raw_headers if col not in column_map]
                        if unmapped_columns:
                            logger.warning(
                                f"表 {original_table_name} 中有 {len(unmapped_columns)} 个列未映射: {unmapped_columns}"
                            )
                    else:
                        # 没有列名映射，直接保留原始表头
                        outfile.write(header_line)
                        logger.warning(f"表 {original_table_name} 没有列名映射，将保留原始列名")

                    # 其余行原样写入
                    row_count = 0
                    for line in infile:
                        outfile.write(line)
                        row_count += 1

                logger.info(f"文件处理成功: {filename} -> {new_table_name}.csv, 共处理 {row_count} 行")
                result["processed_files"].append({
                    "original": filename,
                    "new": f"{new_table_name}.csv",
                    "path": output_path,
                    "rows_processed": row_count,
                    "mapped": True  # 标记为有映射关系
                })
            except Exception as e:
                error_msg = f"处理文件 {filename} 时出错: {str(e)}"
                logger.error(error_msg)
                result["error_files"].append({
                    "file": filename,
                    "error": str(e)
                })
                result["success"] = False
        else:
            # 表名没有映射，原样复制文件
            try:
                import shutil
                shutil.copy2(input_path, output_path)
                logger.info(f"表 {original_table_name} 没有映射，已原样复制到输出目录: {filename}")
                result["copied_files"].append({
                    "file": filename,
                    "path": output_path,
                    "mapped": False  # 标记为无映射关系
                })
            except Exception as e:
                error_msg = f"复制文件 {filename} 时出错: {str(e)}"
                logger.error(error_msg)
                result["error_files"].append({
                    "file": filename,
                    "error": str(e)
                })
                result["success"] = False

    # 汇总处理结果
    logger.info(f"CSV处理完成，共处理 {len(result['processed_files'])} 个有映射的文件，"
                f"原样复制 {len(result['copied_files'])} 个无映射的文件，"
                f"失败 {len(result['error_files'])} 个文件")

    return result