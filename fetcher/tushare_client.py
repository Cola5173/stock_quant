"""
Tushare Pro 客户端初始化（统一入口）
所有需要调用 Tushare 的模块都应从此处导入 pro 实例。
"""
import pandas as pd

# pandas >= 2.2 移除了 fillna(method=...) 参数，tushare 内部仍在使用，需要兼容
_original_df_fillna = pd.DataFrame.fillna
_original_series_fillna = pd.Series.fillna


def _patched_df_fillna(self, value=None, *, method=None, axis=None, inplace=False, limit=None):
    if method is not None:
        if method == "ffill":
            result = self.ffill(axis=axis, limit=limit)
        elif method == "bfill":
            result = self.bfill(axis=axis, limit=limit)
        else:
            return _original_df_fillna(self, value=value, axis=axis, inplace=inplace, limit=limit)
        if inplace:
            self[:] = result
            return None
        return result
    return _original_df_fillna(self, value=value, axis=axis, inplace=inplace, limit=limit)


def _patched_series_fillna(self, value=None, *, method=None, axis=None, inplace=False, limit=None):
    if method is not None:
        if method == "ffill":
            result = self.ffill(axis=axis, limit=limit)
        elif method == "bfill":
            result = self.bfill(axis=axis, limit=limit)
        else:
            return _original_series_fillna(self, value=value, axis=axis, inplace=inplace, limit=limit)
        if inplace:
            self[:] = result
            return None
        return result
    return _original_series_fillna(self, value=value, axis=axis, inplace=inplace, limit=limit)


pd.DataFrame.fillna = _patched_df_fillna
pd.Series.fillna = _patched_series_fillna

import tushare as ts

TUSHARE_TOKEN = "6fab174f9ec5036b8c94759aeb1299ec903b38f6a2d633de4173d475b92f39b0"
TUSHARE_API_URL = "http://124.220.22.110:8020/"

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api(TUSHARE_TOKEN)
pro._DataApi__http_url = TUSHARE_API_URL
