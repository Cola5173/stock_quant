# @Author: cola5173
# @Time: 2025/12/7 03:15

def _normalize_stock_code(stock_code: str) -> str:
    """
    :param stock_code: BaoStock格式的股票代码，如 'sh.000001' 或 'sz.000001'
    :return: 纯数字格式的股票代码，如 '000001' 或 '600000'
    """
    if '.' in stock_code:
        # 去掉前缀 sh. 或 sz.
        return stock_code.split('.')[1]
    return stock_code


def _convert_stock_code(stock_code: str) -> str:
    """
    转换股票代码格式
    BaoStock使用格式：sh.600000, sz.000001
    :param stock_code: 原始股票代码，如 '000001' 或 '600000'
    :return: BaoStock格式的股票代码
    """
    if stock_code.startswith('6'):
        return f'sh.{stock_code}'
    elif stock_code.startswith('0') or stock_code.startswith('3'):
        return f'sz.{stock_code}'
    else:
        # 如果已经是BaoStock格式，直接返回
        if '.' in stock_code:
            return stock_code
        return stock_code
