"""
字段映射字典
将不同数据源的字段名映射到标准字段名
格式：{原始字段名: 标准字段名}
"""


class FieldMapping:
    """字段映射类，用于统一不同数据源的字段名称"""

    # BaoStock字段映射（BaoStock的字段名与标准字段名基本一致）
    BAOSTOCK_FIELD_MAPPING = {
        'date': 'date',
        'code': 'code',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'preclose': 'preclose',
        'volume': 'volume',
        'amount': 'amount',
        'adjustflag': 'adjustflag',
        'turn': 'turn',
        'tradestatus': 'tradestatus',
        'pctChg': 'pctChg',
        'isST': 'isST',
    }
