"""个股详细信息服务（数据来源：Tushare 行情 + 巨潮 公司概况 via AkShare）"""
import os
import contextlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _no_proxy():
    """临时禁用代理（巨潮接口走系统代理可能失败）"""
    saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _to_ts_code(code: str) -> str:
    """纯数字代码 → Tushare 格式（600000 → 600000.SH）"""
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return code


def _fetch_tushare_market(code: str) -> Dict[str, Any]:
    """
    从 Tushare 拉行情数据：最新价、总市值、流通市值、总股本、流通股、PE、PB、行业、上市日期
    Tushare daily_basic 单位：market_cap=万元、share=万股，转回 raw 单位以匹配前端格式化
    """
    out: Dict[str, Any] = {}
    try:
        from api.fetcher.tushare_client import pro
        ts_code = _to_ts_code(code)

        # stock_basic：行业、上市日期、市场
        try:
            sb = pro.stock_basic(ts_code=ts_code, fields="ts_code,name,industry,list_date,market")
            if sb is not None and not sb.empty:
                row = sb.iloc[0]
                if row.get("industry"):
                    out["行业"] = row["industry"]
                if row.get("list_date"):
                    out["上市时间"] = str(row["list_date"])
                if row.get("name"):
                    out["股票简称"] = row["name"]
                out["股票代码"] = code
        except Exception as e:
            logger.debug(f"stock_basic 失败: {e}")

        # daily_basic：找最近 10 个交易日内最新一条
        for offset in range(0, 10):
            try:
                day = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                db = pro.daily_basic(
                    ts_code=ts_code,
                    trade_date=day,
                    fields="trade_date,close,total_mv,circ_mv,total_share,float_share,pe,pb",
                )
                if db is None or db.empty:
                    continue
                row = db.iloc[0]
                # close 直接是元
                if row.get("close") is not None:
                    out["最新"] = float(row["close"])
                # total_mv / circ_mv 单位是万元 → 转回元
                if row.get("total_mv") is not None:
                    out["总市值"] = float(row["total_mv"]) * 1e4
                if row.get("circ_mv") is not None:
                    out["流通市值"] = float(row["circ_mv"]) * 1e4
                # total_share / float_share 单位是万股 → 转回股
                if row.get("total_share") is not None:
                    out["总股本"] = float(row["total_share"]) * 1e4
                if row.get("float_share") is not None:
                    out["流通股"] = float(row["float_share"]) * 1e4
                if row.get("pe") is not None:
                    out["pe"] = round(float(row["pe"]), 2)
                if row.get("pb") is not None:
                    out["pb"] = round(float(row["pb"]), 2)
                break
            except Exception as e:
                logger.debug(f"daily_basic {day} 失败: {e}")
                continue
    except Exception as e:
        logger.warning(f"Tushare 行情拉取失败: {e}")
    return out


def get_stock_info(code: str) -> Optional[Dict[str, Any]]:
    """合并 Tushare 行情 + 巨潮 公司概况"""
    try:
        result: Dict[str, Any] = {}

        # 1. Tushare 行情数据
        result.update(_fetch_tushare_market(code))

        # 2. 巨潮：公司全称、主营业务、法人、注册资本、机构简介等
        try:
            import akshare as ak
            with _no_proxy():
                df_cn = ak.stock_profile_cninfo(symbol=code)
            if df_cn is not None and not df_cn.empty:
                row = df_cn.iloc[0]
                field_map = {
                    "公司名称": "company_name",
                    "英文名称": "company_name_en",
                    "A股简称": "short_name",
                    "法人代表": "legal_representative",
                    "注册资金": "reg_capital",
                    "成立日期": "established_date",
                    "上市日期": "listed_date",
                    "官方网站": "website",
                    "电子邮箱": "email",
                    "联系电话": "telephone",
                    "注册地址": "reg_address",
                    "办公地址": "office_address",
                    "主营业务": "main_business",
                    "经营范围": "business_scope",
                    "机构简介": "introduction",
                    "所属市场": "market",
                    "曾用简称": "former_name",
                }
                for cn_key, en_key in field_map.items():
                    val = row.get(cn_key)
                    if val is not None and str(val) != "None" and str(val).strip():
                        result[en_key] = str(val).strip()
        except Exception as e:
            logger.debug(f"stock_profile_cninfo 失败: {e}")

        return result if result else None
    except Exception as e:
        logger.warning(f"获取 {code} 个股信息失败: {e}")
        return None
