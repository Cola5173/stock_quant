"""
Tushare Pro 客户端初始化（统一入口）

⚠️ 所有需要调用 Tushare 的模块都必须从此处导入 pro / ts 实例，
   不要在其它地方再 `ts.pro_api(...)` 重新初始化，否则会丢掉私有代理 URL。

调用方式（参考）：
    from api.fetcher.tushare_client import pro, ts
    df = pro.index_basic(limit=5)
    df = ts.pro_bar(api=pro, ts_code="000001.SZ", limit=3)

⭐️ 如果出现「Token 不对」错误，检查是否漏了 pro._DataApi__http_url 这行，
   私有代理必须显式设置 __http_url，否则会打到官方接口 https://api.tushare.pro。
"""
import os
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

# 私有代理（必须搭配下方的 __http_url 一起使用，否则会被识别为 Token 不对）
# 支持通过环境变量覆盖（云端部署时把 token 放进 env，避免提交进 git）
TUSHARE_TOKEN = os.environ.get(
    "TUSHARE_TOKEN",
    "23fa576ec57c0fb8d5de277b2c9481e3af7a4566def2d29ba90ee900",
)
TUSHARE_API_URL = os.environ.get(
    "TUSHARE_API_URL",
    "http://118.89.66.41:8010/",
)

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api(TUSHARE_TOKEN)
# ⚠️ 关键：必须设置 __http_url，否则请求会打到官方接口
pro._DataApi__http_url = TUSHARE_API_URL
