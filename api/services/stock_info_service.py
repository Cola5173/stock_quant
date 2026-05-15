"""个股详细信息服务（数据来源：东方财富 + 巨潮 via AkShare）"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def _to_xq_symbol(code: str) -> str:
    """纯数字代码 → 雪球格式（600000 → SH600000，000001 → SZ000001）"""
    if code.startswith("6"):
        return f"SH{code}"
    return f"SZ{code}"


def get_stock_info(code: str) -> Optional[Dict[str, Any]]:
    """
    查询个股基本信息，合并东方财富 + 巨潮两个数据源
    """
    try:
        import akshare as ak
        result: Dict[str, Any] = {}

        # 东方财富：最新价、总市值、流通市值、行业、上市时间
        try:
            df_em = ak.stock_individual_info_em(symbol=code)
            if df_em is not None and not df_em.empty:
                for _, row in df_em.iterrows():
                    result[str(row["item"])] = row["value"]
        except Exception as e:
            logger.debug(f"stock_individual_info_em 失败: {e}")

        # 巨潮：公司全称、主营业务、法人、注册资本、经营范围、机构简介等
        try:
            df_cn = ak.stock_profile_cninfo(symbol=code)
            if df_cn is not None and not df_cn.empty:
                row = df_cn.iloc[0]
                field_map = {
                    "公司名称": "company_name",
                    "英文名称": "company_name_en",
                    "A股简称": "short_name",
                    "所属行业": "industry",
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
