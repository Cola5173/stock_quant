"""
测试脚本：获取所有A股股票代码并保存到CSV文件
将股票代码保存到一个CSV文件中，每行一个股票代码
"""
import os
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta


def is_valid_stock_code(code: str) -> bool:
    """
    判断是否为有效的A股股票代码
    :param code: 股票代码，格式：sh.600000 或 sz.000001
    :return: 是否为有效股票代码
    """
    if not code or '.' not in code:
        return False
    
    parts = code.split('.')
    if len(parts) != 2:
        return False
    
    market = parts[0]  # sh 或 sz
    stock_num = parts[1]  # 股票代码数字部分
    
    # 上海股票：sh.600xxx, sh.601xxx, sh.603xxx, sh.605xxx, sh.688xxx
    if market == 'sh':
        if stock_num.startswith('600') or stock_num.startswith('601') or \
           stock_num.startswith('603') or stock_num.startswith('605') or \
           stock_num.startswith('688'):
            return True
    
    # 深圳股票：sz.000xxx, sz.001xxx, sz.002xxx, sz.300xxx
    elif market == 'sz':
        if stock_num.startswith('000') or stock_num.startswith('001') or \
           stock_num.startswith('002') or stock_num.startswith('300'):
            return True
    
    return False


def get_stock_list() -> list:
    """
    获取所有A股股票列表
    :return: 股票代码列表（格式：sh.600000 或 sz.000001）
    """
    print("正在获取A股股票列表...")
    stock_list = []

    # 尝试最近几个日期，找到有效的交易日
    today = datetime.now()
    for days_back in range(0, 5):
        test_date = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
        rs = bs.query_all_stock(day=test_date)

        if rs.error_code == '0':
            has_data = False
            while rs.next():
                has_data = True
                data = rs.get_row_data()
                if data and len(data) > 0:
                    code = data[0]  # 股票代码，格式：sh.600000 或 sz.000001
                    # 只添加有效的股票代码
                    if is_valid_stock_code(code):
                        stock_list.append(code)

            if has_data and len(stock_list) > 0:
                print(f"使用交易日 {test_date} 获取股票列表，共 {len(stock_list)} 只股票")
                return stock_list

    # 如果所有日期都失败，尝试不指定日期
    print("尝试使用默认方式获取股票列表...")
    rs = bs.query_all_stock()

    if rs.error_code != '0':
        print(f'获取股票列表失败: {rs.error_msg}')
        return []

    while rs.next():
        data = rs.get_row_data()
        if data and len(data) > 0:
            code = data[0]
            # 只添加有效的股票代码
            if is_valid_stock_code(code):
                stock_list.append(code)

    if len(stock_list) > 0:
        print(f"获取股票列表成功，共 {len(stock_list)} 只股票")
    else:
        print('警告: 获取股票列表为空')

    return stock_list


def save_stock_codes_to_csv(stock_list: list, output_file: str) -> bool:
    """
    将股票代码列表保存到CSV文件
    :param stock_list: 股票代码列表
    :param output_file: 输出文件路径
    :return: 是否保存成功
    """
    try:
        # 创建DataFrame，每行一个股票代码
        df = pd.DataFrame(stock_list)

        # 保存到CSV文件，不包含列名
        df.to_csv(output_file, index=False, header=False, encoding='utf-8-sig')
        print(f"股票代码已保存到: {output_file}")
        print(f"共保存 {len(stock_list)} 个股票代码")
        return True

    except Exception as e:
        print(f"保存股票代码失败: {e}")
        return False


def test_download_all_stocks():
    """
    获取所有A股股票代码并保存到CSV文件
    """
    # 设置输出文件
    output_file = "stock_code.csv"

    print("=" * 60)
    print("开始测试：获取所有A股股票代码")
    print("=" * 60)
    print(f"输出文件: {output_file}")
    print("-" * 60)

    # 登录BaoStock
    print("正在登录BaoStock...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"BaoStock登录失败: {lg.error_msg}")
        return

    print("BaoStock登录成功！")
    print("-" * 60)

    try:
        # 获取所有股票列表
        stock_list = get_stock_list()

        if not stock_list:
            print("未获取到股票列表，退出")
            return

        print("-" * 60)

        # 保存股票代码到CSV文件
        if save_stock_codes_to_csv(stock_list, output_file):
            print("-" * 60)
            print("完成！")
            print(f"所有股票代码已保存到 {output_file}")

            # 显示前10个股票代码作为示例
            if stock_list:
                print("\n示例股票代码（前10个）：")
                for i, code in enumerate(sorted(stock_list)[:10], 1):
                    print(f"  {i}. {code}")
        else:
            print("保存失败！")

    except Exception as e:
        print(f"处理过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 登出BaoStock
        bs.logout()
        print("已登出BaoStock")


if __name__ == '__main__':
    test_download_all_stocks()
