"""V2 ML 版扫描：用 GBM 模型从 b1_v2 数据中学到的评分公式

用法:
    python tests/scan_v2_ml.py 2026-05-15 --workers 8

模型在 /tmp/v2_score_gbm.pkl，包含训练好的 GradientBoostingRegressor 和特征列表。
"""
import os
import sys
import json
import pickle
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from glob import glob

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy


MODEL_PATH = "/tmp/v2_score_gbm.pkl"
_NAME_MAP: dict = {}
_MODEL = None
_FEATURES = None


def _load_model():
    global _MODEL, _FEATURES
    if _MODEL is None:
        with open(MODEL_PATH, "rb") as f:
            d = pickle.load(f)
        _MODEL = d["model"]
        _FEATURES = d["features"]
    return _MODEL, _FEATURES


def _load_name_map() -> dict:
    global _NAME_MAP
    if _NAME_MAP:
        return _NAME_MAP
    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "api", "resource", "stock_names.csv"
    )
    if not os.path.exists(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path, dtype={"symbol": str})
        _NAME_MAP = dict(zip(df["symbol"].astype(str).str.strip(),
                             df["name"].astype(str).str.strip()))
    except Exception:
        _NAME_MAP = {}
    return _NAME_MAP


def list_symbols() -> list:
    files = glob(os.path.join(settings.DATA_DIR, "*.csv"))
    out = []
    for f in files:
        n = os.path.basename(f).replace(".csv", "")
        if n.isdigit() and len(n) == 6:
            out.append(n)
    return sorted(out)


def extract_features(symbol: str, end_date: str):
    csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path)
        for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                    KLineConstants.CLOSE, KLineConstants.VOLUME]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
        df = df[df[KLineConstants.DATE] <= pd.to_datetime(end_date)]
        df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
    except Exception:
        return None

    if df.empty or len(df) < 30:
        return None
    last_date = df[KLineConstants.DATE].iloc[-1].date().isoformat()
    if last_date != end_date:
        return None

    closes = df[KLineConstants.CLOSE].values.astype(float)
    opens = df[KLineConstants.OPEN].values.astype(float)
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)

    if len(closes) >= 2 and closes[-2] > 0:
        pct = (closes[-1] - closes[-2]) / closes[-2] * 100
        limit = 20.0 if (symbol.startswith("30") or symbol.startswith("68")) else 10.0
        if pct >= limit - 0.1:
            return None

    yellow = B1Strategy._yellow_series(closes)
    white = pd.Series(closes).ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values
    j_arr = B1Strategy._j_series(highs, lows, closes)

    cur_close = float(closes[-1])
    cur_yellow = float(yellow[-1])
    cur_white = float(white[-1])
    if cur_yellow <= 0 or cur_white <= 0:
        return None

    vol_ma5 = float(np.mean(volumes[-6:-1])) if len(volumes) >= 6 else 0
    vol_ratio = volumes[-1] / vol_ma5 if vol_ma5 > 0 else 1.0
    chg_pct = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] > 0 else 0.0
    cur_j = float(j_arr[-1])

    dev_white = (cur_close / cur_white - 1) * 100
    dev_long = (cur_close / cur_yellow - 1) * 100
    white_slope_5 = ((white[-1] / white[-6]) - 1) * 100 if len(white) >= 6 else 0
    white_slope_10 = ((white[-1] / white[-11]) - 1) * 100 if len(white) >= 11 else 0
    yellow_slope_5 = ((yellow[-1] / yellow[-6]) - 1) * 100 if len(yellow) >= 6 else 0
    yellow_slope_10 = ((yellow[-1] / yellow[-11]) - 1) * 100 if len(yellow) >= 11 else 0
    volatility_10 = float(np.std(closes[-10:]) / np.mean(closes[-10:]) * 100) if len(closes) >= 10 else 0
    if len(volumes) >= 15:
        avg_old = float(np.mean(volumes[-15:-5]))
        vol_compress = float(np.mean(volumes[-5:])) / avg_old if avg_old > 0 else 1.0
    else:
        vol_compress = 1.0
    ret_5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    ret_10 = (closes[-1] / closes[-11] - 1) * 100 if len(closes) >= 11 else 0

    if (highs[-1] - lows[-1]) > 0:
        rng = highs[-1] - lows[-1]
        upper_pct = (highs[-1] - max(closes[-1], opens[-1])) / rng * 100
        lower_pct = (min(closes[-1], opens[-1]) - lows[-1]) / rng * 100
    else:
        upper_pct = 0
        lower_pct = 0

    above_white = 1 if cur_close > cur_white else 0
    white_above_yellow = (cur_white / cur_yellow - 1) * 100

    feat = {
        "kdj_j": cur_j, "vol_ratio": vol_ratio, "chg_pct": chg_pct,
        "dev_white": dev_white, "dev_long": dev_long,
        "white_slope_5": white_slope_5, "white_slope_10": white_slope_10,
        "yellow_slope_5": yellow_slope_5, "yellow_slope_10": yellow_slope_10,
        "volatility_10": volatility_10, "vol_compress": vol_compress,
        "ret_5": ret_5, "ret_10": ret_10,
        "upper_pct": upper_pct, "lower_pct": lower_pct,
        "above_white": above_white, "white_above_yellow": white_above_yellow,
    }
    indicators = {
        "kdj_j": round(cur_j, 2),
        "trend_long": round(cur_yellow, 2),
        "trend_white": round(cur_white, 2),
        "vol_ratio": round(vol_ratio, 3),
        "chg_pct": round(chg_pct, 3),
        "dev_long_pct": round(dev_long, 3),
        "white_above_yellow_pct": round(white_above_yellow, 3),
        "volatility_10": round(volatility_10, 3),
    }
    return cur_close, feat, indicators


def check_one(args: tuple):
    symbol, end_date = args
    name_map = _load_name_map()
    model, features = _load_model()

    res = extract_features(symbol, end_date)
    if res is None:
        return None
    cur_close, feat, indicators = res

    X = np.array([[feat[k] for k in features]])
    score = float(model.predict(X)[0])

    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": end_date,
        "close": round(cur_close, 2),
        "score": round(score, 2),
        "indicators": indicators,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    symbols = list_symbols()
    print(f"扫描日: {args.date} | 股票总数: {len(symbols)} | 并发: {args.workers}")
    print(f"模型: {MODEL_PATH}")

    t0 = datetime.now()
    results = []
    tasks = [(s, args.date) for s in symbols]
    with ProcessPoolExecutor(max_workers=args.workers) as exe:
        futures = {exe.submit(check_one, t): t[0] for t in tasks}
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)
            done += 1
            if done % 1000 == 0 or done == len(tasks):
                el = (datetime.now() - t0).total_seconds()
                print(f"  进度 {done}/{len(tasks)}  耗时 {el:.1f}s", flush=True)

    results.sort(key=lambda x: -x["score"])

    date_part = args.date.replace("-", "_")
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "selected", f"{date_part}_v2_ml")
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "result.json")
    out = {
        "scan_date": args.date,
        "strategy": "v2_ml",
        "total_scanned": len(symbols),
        "candidates_count": len(results),
        "candidates": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n命中 {len(results)} 只，保存到 {out_path}")
    print(f"\n=== Top {args.top} ===")
    for r in results[:args.top]:
        ind = r["indicators"]
        print(f"  {r['symbol']:>7} {r['name']:>10s}  分{r['score']:>+6.2f}  "
              f"close={ind['trend_long']:>7.2f}*{r['close']/ind['trend_long']:.4f}  "
              f"白>黄={ind['white_above_yellow_pct']:>+5.2f}%  "
              f"vol_r={ind['vol_ratio']:>5.2f}  vola={ind['volatility_10']:>5.2f}%")


if __name__ == "__main__":
    main()
import os
import sys
import json
import pickle
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from glob import glob

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy


MODEL_PATH = "/tmp/v2_score_gbm.pkl"
_NAME_MAP: dict = {}
_MODEL = None
_FEATURES = None


def _load_model():
    global _MODEL, _FEATURES
    if _MODEL is None:
        with open(MODEL_PATH, "rb") as f:
            d = pickle.load(f)
        _MODEL = d["model"]
        _FEATURES = d["features"]
    return _MODEL, _FEATURES


def _load_name_map() -> dict:
    global _NAME_MAP
    if _NAME_MAP:
        return _NAME_MAP
    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "api", "resource", "stock_names.csv"
    )
    if not os.path.exists(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path, dtype={"symbol": str})
        _NAME_MAP = dict(zip(df["symbol"].astype(str).str.strip(),
                             df["name"].astype(str).str.strip()))
    except Exception:
        _NAME_MAP = {}
    return _NAME_MAP


def list_symbols() -> list:
    files = glob(os.path.join(settings.DATA_DIR, "*.csv"))
    out = []
    for f in files:
        n = os.path.basename(f).replace(".csv", "")
        if n.isdigit() and len(n) == 6:
            out.append(n)
    return sorted(out)


def extract_features(symbol: str, end_date: str):
    """计算与训练时同样的 17 个特征。返回 (feature_dict, indicators_dict) 或 None"""
    csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path)
        for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                    KLineConstants.CLOSE, KLineConstants.VOLUME]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
        df = df[df[KLineConstants.DATE] <= pd.to_datetime(end_date)]
        df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
    except Exception:
        return None

    if df.empty or len(df) < 30:
        return None
    last_date = df[KLineConstants.DATE].iloc[-1].date().isoformat()
    if last_date != end_date:
        return None

    closes = df[KLineConstants.CLOSE].values.astype(float)
    opens = df[KLineConstants.OPEN].values.astype(float)
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)

    # 涨停过滤
    if len(closes) >= 2 and closes[-2] > 0:
        pct = (closes[-1] - closes[-2]) / closes[-2] * 100
        limit = 20.0 if (symbol.startswith("30") or symbol.startswith("68")) else 10.0
        if pct >= limit - 0.1:
            return None

    yellow = B1Strategy._yellow_series(closes)
    white = pd.Series(closes).ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values
    j_arr = B1Strategy._j_series(highs, lows, closes)

    cur_close = float(closes[-1])
    cur_yellow = float(yellow[-1])
    cur_white = float(white[-1])
    if cur_yellow <= 0 or cur_white <= 0:
        return None

    # 量比
    vol_ratio = volumes[-1] / float(np.mean(volumes[-6:-1])) if len(volumes) >= 6 and float(np.mean(volumes[-6:-1])) > 0 else 1.0
    chg_pct = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] > 0 else 0.0
    cur_j = float(j_arr[-1])

    # 衍生特征（与训练时完全一致）
    dev_white = (cur_close / cur_white - 1) * 100
    dev_long = (cur_close / cur_yellow - 1) * 100
    white_slope_5 = ((white[-1] / white[-6]) - 1) * 100 if len(white) >= 6 else 0
    white_slope_10 = ((white[-1] / white[-11]) - 1) * 100 if len(white) >= 11 else 0
    yellow_slope_5 = ((yellow[-1] / yellow[-6]) - 1) * 100 if len(yellow) >= 6 else 0
    yellow_slope_10 = ((yellow[-1] / yellow[-11]) - 1) * 100 if len(yellow) >= 11 else 0
    volatility_10 = float(np.std(closes[-10:]) / np.mean(closes[-10:]) * 100) if len(closes) >= 10 else 0
    if len(volumes) >= 15:
        vol_compress = float(np.mean(volumes[-5:])) / float(np.mean(volumes[-15:-5])) if float(np.mean(volumes[-15:-5])) > 0 else 1.0
    else:
        vol_compress = 1.0
    ret_5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    ret_10 = (closes[-1] / closes[-11] - 1) * 100 if len(closes) >= 11 else 0

    if (highs[-1] - lows[-1]) > 0:
        rng = highs[-1] - lows[-1]
        upper_pct = (highs[-1] - max(closes[-1], opens[-1])) / rng * 100
        lower_pct = (min(closes[-1], opens[-1]) - lows[-1]) / rng * 100
    else:
        upper_pct = 0
        lower_pct = 0

    above_white = 1 if cur_close > cur_white else 0
    white_above_yellow = (cur_white / cur_yellow - 1) * 100

    feat = {
        "kdj_j": cur_j, "vol_ratio": vol_ratio, "chg_pct": chg_pct,
        "dev_white": dev_white, "dev_long": dev_long,
        "white_slope_5": white_slope_5, "white_slope_10": white_slope_10,
        "yellow_slope_5": yellow_slope_5, "yellow_slope_10": yellow_slope_10,
        "volatility_10": volatility_10, "vol_compress": vol_compress,
        "ret_5": ret_5, "ret_10": ret_10,
        "upper_pct": upper_pct, "lower_pct": lower_pct,
        "above_white": above_white, "white_above_yellow": white_above_yellow,
    }
    indicators = {
        "kdj_j": round(cur_j, 2),
        "trend_long": round(cur_yellow, 2),
        "trend_white": round(cur_white, 2),
        "vol_ratio": round(vol_ratio, 3),
        "chg_pct": round(chg_pct, 3),
        "dev_long_pct": round(dev_long, 3),
        "white_above_yellow_pct": round(white_above_yellow, 3),
        "volatility_10": round(volatility_10, 3),
    }
    return cur_close, feat, indicators


def check_one(args: tuple):
    symbol, end_date = args
    name_map = _load_name_map()
    model, features = _load_model()

    res = extract_features(symbol, end_date)
    if res is None:
        return None
    cur_close, feat, indicators = res

    # 特征排序与训练时一致
    X = np.array([[feat[k] for k in features]])
    score = float(model.predict(X)[0])

    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": end_date,
        "close": round(cur_close, 2),
        "score": round(score, 2),
        "indicators": indicators,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    symbols = list_symbols()
    print(f"扫描日: {args.date} | 股票总数: {len(symbols)} | 并发: {args.workers}")
    print(f"模型: {MODEL_PATH}")

    t0 = datetime.now()
    results = []
    tasks = [(s, args.date) for s in symbols]
    with ProcessPoolExecutor(max_workers=args.workers) as exe:
        futures = {exe.submit(check_one, t): t[0] for t in tasks}
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)
            done += 1
            if done % 1000 == 0 or done == len(tasks):
                el = (datetime.now() - t0).total_seconds()
                print(f"  进度 {done}/{len(tasks)} 耗时 {el:.1f}s", flush=True)

    results.sort(key=lambda x: -x["score"])

    date_part = args.date.replace("-", "_")
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "selected", f"{date_part}_v2ml")
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "result.json")
    out = {
        "scan_date": args.date,
        "strategy": "v2_ml",
        "total_scanned": len(symbols),
        "candidates_count": len(results),
        "candidates": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n命中 {len(results)} 只，保存到 {out_path}")
    print(f"\n=== Top {args.top} ===")
    for r in results[:args.top]:
        ind = r["indicators"]
        print(f"  {r['symbol']:>7} {r['name']:>10s}  分{r['score']:>5.2f}  "
              f"close={r['close']:>7.2f}  long={ind['trend_long']:>7.2f}  "
              f"dev_l={ind['dev_long_pct']:>+5.2f}%  W>Y={ind['white_above_yellow_pct']:>+5.2f}%  "
              f"vol_r={ind['vol_ratio']:>5.2f}  chg={ind['chg_pct']:>+5.2f}%  J={ind['kdj_j']:>+5.1f}")


if __name__ == "__main__":
    main()
