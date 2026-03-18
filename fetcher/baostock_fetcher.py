"""
BaoStock数据获取模块
使用BaoStock数据源获取股票数据（免费，稳定）
"""
import pandas as pd
import os
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from .fetcher import DataFetcher
from model.kline_constants import KLineConstants
from config import settings
from utils.utils import _normalize_stock_code, _convert_stock_code


class BaoStockDataFetcher(DataFetcher):
    """使用BaoStock数据源（免费，稳定）"""

    def __init__(self):
        """
        初始化BaoStock数据获取器
        BaoStock是免费的A股数据接口，数据稳定可靠
        """
        super().__init__()
        try:
            import baostock as bs
            self.bs = bs
            # 登录系统
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f'BaoStock登录失败: {lg.error_msg}')
            self._logged_in = True
        except ImportError:
            raise ImportError("请先安装baostock: pip install baostock")
        except Exception as e:
            print(f"BaoStock初始化失败: {e}")
            self._logged_in = False

    def get_last_trade_date(self) -> str:
        """
        获取最近的有效的交易日
        通过查询参考股票的数据来确定最近的交易日
        :return: 最近的交易日，格式：'YYYY-MM-DD'
        """
        if not self._logged_in:
            print("BaoStock未登录，无法获取交易日")
            return datetime.now().strftime('%Y-%m-%d')

        reference_stock = settings.REFERENCE_STOCK  # 参考股票代码，如 'sh.000001'

        # 从今天开始往前查找，最多查找10天
        today = datetime.now()
        for days_back in range(0, 10):
            test_date = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')

            # 查询参考股票在测试日期的数据
            rs = self.bs.query_history_k_data_plus(
                reference_stock,
                KLineConstants.DATE,
                start_date=test_date,
                end_date=test_date,
                frequency="d",
                adjustflag="2"
            )

            # 如果查询成功且有数据，说明这一天是交易日
            if rs.error_code == '0':
                data_list = []
                while rs.next():
                    data_list.append(rs.get_row_data())

                if data_list and len(data_list) > 0:
                    # 找到有效交易日，返回日期
                    return test_date

        # 如果10天内都没找到，返回今天（作为默认值）
        return today.strftime('%Y-%m-%d')

    def fetch(self,
              start_date: Optional[str] = None,
              end_date: Optional[str] = None) -> None:
        """
        批量下载股票数据到指定目录
        :param start_date: 起始日期，格式：'YYYY-MM-DD'，如果不指定则下载最近一个交易日
        :param end_date: 结束日期，格式：'YYYY-MM-DD'，如果不指定则使用start_date（下载单日数据）
        :param data_dir: 数据保存目录，默认"data"
        """
        from tqdm import tqdm

        if not self._logged_in:
            print("BaoStock未登录，无法下载数据")
            return

        try:
            # 创建数据目录
            os.makedirs(settings.DATA_DIR, exist_ok=True)

            # 获取所有股票列表
            print(f"step 1.1: ----> 获取所有A股股票列表...")
            stock_codes = self._get_all_stock_codes()
            total_stocks = len(stock_codes)

            if total_stocks == 0:
                print("未获取到股票列表")
                return
            print(f"共 {total_stocks} 只股票")

            # 获取需要拉取数据的股票集合
            print(f"step 1.2: ----> 获取需要拉取数据的股票集合...")
            stocks_to_download = self._classify_stocks_for_download(
                stock_codes
            )
            print(f"需要拉取: {len(stocks_to_download)} 只股票, 分别是: {stocks_to_download}")

            print(f"step 1.3: ----> 开始下载K线数据...")
            failed_count = 0
            success_count = 0
            index = 0
            for stock_code in tqdm(stocks_to_download, desc="下载数据"):
                try:
                    index += 1
                    normalized_stock_code = _normalize_stock_code(stock_code)
                    # 获取最近的交易日，字符串格式 'YYYY-MM-DD'
                    end_date_str = self.get_last_trade_date()
                    # 用于 DataFrame 比较时转为 Timestamp
                    end_date_ts = pd.to_datetime(end_date_str)
                    print(f"step 1.3.1: ----> 下载第 {index} 只股票: {normalized_stock_code}")

                    # 1. 获取data目录下的数据（历史已保存部分）
                    df = self._load_stock_data(normalized_stock_code)

                    # 1.1 如果df为空，那就直接下载至最近交易日
                    if df.empty:
                        df = self.get_stock_data(normalized_stock_code, start_date, end_date_str)
                    else:
                        # 1.2 如果df不为空，那就增量下载缺失的部分
                        # 获取本地数据中最大的交易日
                        max_date = df[KLineConstants.DATE].max()
                        # 如果本地最新日期早于实际最新交易日，则补齐缺失数据
                        if max_date < end_date_ts:
                            df = self.get_stock_data(normalized_stock_code,
                                                     (max_date + timedelta(days=1)).strftime('%Y-%m-%d'),
                                                     end_date_str)
                        else:
                            df = None
                    # 2. 追加保存数据
                    if df is not None:
                        self._save_stock_data(normalized_stock_code, df)
                    else:
                        continue
                    success_count += 1
                except Exception as e:
                    failed_count += 1
                    print(f"下载股票 {stock_code} 数据失败: {e}")
                    continue

            print(f"step 1.4: ----> 下载完成！")
            print(f"  - 成功: {success_count} 只股票")
            print(f"  - 失败: {failed_count} 只股票")

        except Exception as e:
            print(f"批量下载数据失败: {e}")

    def _classify_stocks_for_download(self,
                                      stock_list: List[str],
                                      ) -> Set[str]:
        """
        分类股票，判断哪些需要拉取数据

        :param stock_list: 股票代码列表
        :return: set，包含需要拉取数据的股票代码
        """
        stocks_to_download = set()  # 需要拉取数据的股票集合

        # 获取实际的最后交易日（而不是用户输入的日期）
        actual_last_trade_date_str = self.get_last_trade_date()
        # 转换为 Timestamp 类型以便比较
        actual_last_trade_date = pd.to_datetime(actual_last_trade_date_str)

        # 1. 遍历股票列表
        for stock_code in stock_list:
            normalized_stock_code = _normalize_stock_code(stock_code)
            file_path = self._get_stock_file_path(normalized_stock_code)

            # 2. 检查文件是否存在
            if os.path.exists(file_path):
                try:
                    # 2.1 加载文件数据
                    existing_df = pd.read_csv(file_path)

                    # 2.2 检查数据是否正常
                    if existing_df.empty or KLineConstants.DATE not in existing_df.columns:
                        # 数据异常，需要重新拉取
                        stocks_to_download.add(stock_code)
                        continue

                    # 2.3 转换日期格式并检查数据是否完整
                    existing_df[KLineConstants.DATE] = pd.to_datetime(existing_df[KLineConstants.DATE])
                    last_date = existing_df[KLineConstants.DATE].max()

                    # 如果最新日期小于实际最后交易日，说明数据不完整，需要拉取
                    if last_date < actual_last_trade_date:
                        stocks_to_download.add(stock_code)
                    else:
                        # print(f"股票 {stock_code} 数据已完整，跳过")
                        continue
                except Exception as e:
                    # 文件读取失败或数据异常，需要重新拉取
                    print(f"读取股票 {stock_code} 数据文件失败: {e}")
                    stocks_to_download.add(stock_code)
            else:
                # 2.4 文件不存在，需要拉取数据
                stocks_to_download.add(stock_code)

        return stocks_to_download

    def get_stock_data(self,
                       stock_code: str,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> pd.DataFrame:
        """
        获取股票历史数据，从BaoStock获取数据，并转换为DataFrame
        :param stock_code: 股票代码（如 '000001' 或 '600000'）
        :param start_date: 开始日期，格式：'YYYY-MM-DD'
        :param end_date: 结束日期，格式：'YYYY-MM-DD'
        :return: DataFrame，包含日期、开盘、收盘、最高、最低、成交量等
        """
        if not self._logged_in:
            print("BaoStock未登录，无法获取股票数据")
            return pd.DataFrame()

        try:
            # 转换股票代码格式
            bs_code = _convert_stock_code(stock_code)

            # 设置日期范围
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if not start_date:
                # 默认获取最近30天的数据（考虑非交易日，多获取一些）
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

            # 查询历史K线数据
            # BaoStock字段说明：
            # - date: 交易日期
            # - code: 股票代码
            # - open: 开盘价
            # - high: 最高价
            # - low: 最低价
            # - close: 收盘价
            # - preclose: 前收盘价（前一个交易日的收盘价）
            # - volume: 成交量（手，1手=100股）
            # - amount: 成交额（元）
            # - adjustflag: 复权状态（1=后复权, 2=前复权, 3=不复权）
            # - turn: 换手率（%）
            # - tradestatus: 交易状态（1=正常交易, 0=停牌）
            # - pctChg: 涨跌幅（%）
            # - isST: 是否ST股票（1=是, 0=否）
            rs = self.bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                start_date=start_date,
                end_date=end_date,
                frequency="d",  # 日线
                adjustflag="2"  # 前复权（1=后复权, 2=前复权, 3=不复权）
            )

            if rs.error_code != '0':
                print(f'获取股票 {stock_code} 数据失败: {rs.error_msg}')
                return pd.DataFrame()

            # 获取数据并转换为DataFrame
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                return pd.DataFrame()

            # 转换为DataFrame
            df = pd.DataFrame(data_list, columns=rs.fields)

            # 数据类型转换（将字符串转换为数值类型）
            # 这些字段都是数值型字段，需要转换为数字类型以便后续计算
            numeric_columns = [
                'open',  # 开盘价
                'high',  # 最高价
                'low',  # 最低价
                'close',  # 收盘价
                'preclose',  # 前收盘价
                'volume',  # 成交量（手）
                'amount',  # 成交额（元）
                'turn',  # 换手率（%）
                'pctChg'  # 涨跌幅（%）
            ]
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # 转换日期格式
            df['date'] = pd.to_datetime(df['date'])

            # 标准化列名（保持与其他数据源一致）
            df = df.rename(columns={
                'open': 'open',
                'close': 'close',
                'high': 'high',
                'low': 'low',
                'volume': 'volume',
                'amount': 'amount'
            })

            # 按日期排序
            df = df.sort_values('date').reset_index(drop=True)

            return df

        except Exception as e:
            print(f"获取股票 {stock_code} 数据失败: {e}")
            return pd.DataFrame()
