"""
K线数据常量定义
用于统一不同数据源（BaoStock、Tushare等）的字段名称和数据格式
"""


class KLineConstants:
    """K线数据常量类，用于统一数据字段定义"""

    # ========== 标准字段列表（CSV表头） ==========
    # 这些字段用于保存到CSV文件时的表头
    STANDARD_COLUMNS = [
        'date',  # 交易日期
        'code',  # 股票代码（原始格式，如 sz.000001）
        'stock_code',  # 股票代码（标准化格式，如 000001）
        'adjustflag',  # 复权状态（1=后复权, 2=前复权, 3=不复权）
        'open',  # 开盘价
        'high',  # 最高价
        'low',  # 最低价
        'close',  # 收盘价
        'preclose',  # 前收盘价（前一个交易日的收盘价）
        'volume',  # 成交量（手，1手=100股）
        'amount',  # 成交额（元）
        'turn',  # 换手率（%）
        'tradestatus',  # 交易状态（1=正常交易, 0=停牌）
        'pctChg',  # 涨跌幅（%）
        'isST',  # 是否ST股票（1=是, 0=否）
    ]

    # ========== 字段名称常量 ==========
    # 用于通过名称访问字段，避免拼写错误
    DATE = 'date'
    CODE = 'code'
    STOCK_CODE = 'stock_code'
    ADJUSTFLAG = 'adjustflag'
    OPEN = 'open'
    HIGH = 'high'
    LOW = 'low'
    CLOSE = 'close'
    PRECLOSE = 'preclose'
    VOLUME = 'volume'
    AMOUNT = 'amount'
    TURN = 'turn'
    TRADESTATUS = 'tradestatus'
    PCTCHG = 'pctChg'
    ISST = 'isST'
