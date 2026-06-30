"""
DirProbe-v1 下一根 15m 方向「命中率」離線量測（不是策略損益回測）。
把 strategy 內完全相同的 DirProbe-v1 邏輯套到已下載的 15m 歷史資料，
計算：方向命中率、覆蓋率、依信心分桶命中率、依市況(ADX)分組命中率、
並對比 base rate / always-up，附 Wilson 95% 信賴區間。

用法（容器內）：
  docker compose run --rm --entrypoint python freqtrade /freqtrade/user_data/analyze_forecast_history.py
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd
import talib

DATA_DIR = Path("/freqtrade/user_data/data/binance")
PAIRS = ["BTC_USDT", "ETH_USDT"]
TF = "15m"

# DirProbe-v1 參數（與 TrendMomentumV1 一致）
K, NVOL, S, VOLW, BAND = 8, 96, 2.0, 20, 0.10


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def dirprobe(df):
    logc = np.log(df["close"])
    slope = talib.LINEARREG_SLOPE(logc.values, timeperiod=K)
    vol = logc.diff().rolling(NVOL).std().values
    mom_z = slope / (vol + 1e-9)
    mom_s = np.tanh(mom_z / S)
    adx = talib.ADX(df["high"].values, df["low"].values, df["close"].values, timeperiod=14)
    regime = np.clip((adx - 20.0) / 15.0, 0.0, 1.0)

    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body = (df["close"] - df["open"]) / rng
    clv = (2 * df["close"] - df["high"] - df["low"]) / rng
    vsma = df["volume"].rolling(VOLW, min_periods=VOLW).mean()
    vconf = ((df["volume"] / vsma).clip(0.5, 2.0) - 0.5) / 1.5
    micro_s = ((0.5 * body + 0.5 * clv) * vconf).fillna(0.0).values

    fc_score = np.clip(mom_s * (0.4 + 0.6 * regime), -1, 1)
    fc_score = np.nan_to_num(fc_score, nan=0.0)
    fc_dir = np.where(fc_score > BAND, "up", np.where(fc_score < -BAND, "down", "neutral"))
    agree = (np.sign(fc_score) == np.sign(micro_s)) & (micro_s != 0)
    fc_conf = np.clip(np.abs(fc_score) * np.where(agree, 1.0, 0.6), 0, 1)
    fc_conf = np.where(fc_dir == "neutral", 0.0, fc_conf)

    out = pd.DataFrame({"close": df["close"].values, "adx": adx,
                        "fc_dir": fc_dir, "fc_conf": fc_conf})
    # realized 是「標籤」（次根方向），離線量測用未來值正確；不回灌進特徵
    nxt = out["close"].shift(-1)
    out["realized"] = np.where(nxt > out["close"], "up",
                               np.where(nxt < out["close"], "down", "flat"))
    return out


def report(name, d):
    # 只取有方向預測且次根非平盤、且非最後一根
    e = d[(d["fc_dir"] != "neutral") & (d["realized"] != "flat")].copy()
    e = e[e["realized"].notna()]
    n_all = len(d)
    n = len(e)
    print(f"\n===== {name} =====")
    print(f"總根數 {n_all} | 可評估(出方向且次根非平盤) {n} | 覆蓋率 {n / n_all:.1%}")
    if n == 0:
        print("無可評估樣本"); return
    hit = (e["fc_dir"] == e["realized"]).astype(int)
    acc = hit.mean()
    lo, hi = wilson(hit.sum(), n)
    base_up = (e["realized"] == "up").mean()
    majority = max(base_up, 1 - base_up)
    print(f"方向命中率 {acc:.4f}  (Wilson95% [{lo:.4f}, {hi:.4f}])")
    print(f"base rate(次根上漲占比) {base_up:.4f} | 多數類基準(always-{'up' if base_up>=0.5 else 'down'}) {majority:.4f}")
    print(f"相對多數類 edge {acc - majority:+.4f}  | 綜合 edge(覆蓋率×edge) {(n/n_all)*(acc-majority):+.4f}")

    # 依信心分桶（等頻 4 桶）
    print("-- 依信心分桶(等頻) --")
    try:
        e["bucket"] = pd.qcut(e["fc_conf"], 4, duplicates="drop")
        for b, g in e.groupby("bucket", observed=True):
            h = (g["fc_dir"] == g["realized"]).astype(int)
            print(f"  conf {str(b):28s} n={len(g):6d} 命中 {h.mean():.4f}")
    except ValueError:
        print("  (信心值變異不足，無法分桶)")

    # 依市況分組
    print("-- 依市況(ADX@預測時) --")
    for lab, mask in [("盤整 adx<20", e["adx"] < 20),
                      ("過渡 20-25", (e["adx"] >= 20) & (e["adx"] < 25)),
                      ("趨勢 adx>=25", e["adx"] >= 25)]:
        g = e[mask]
        if len(g):
            h = (g["fc_dir"] == g["realized"]).astype(int)
            print(f"  {lab:14s} n={len(g):6d} 命中 {h.mean():.4f}")


pool = []
for p in PAIRS:
    f = DATA_DIR / f"{p}-{TF}.feather"
    if not f.exists():
        print(f"缺資料 {f}（先 download-data）"); continue
    df = pd.read_feather(f).sort_values("date").reset_index(drop=True)
    d = dirprobe(df)
    # 各 pair 自身時間序前 70% = train、後 30% = test（out-of-sample 穩定度）
    d["seg"] = np.where(np.arange(len(d)) < int(len(d) * 0.7), "train", "test")
    report(p, d)
    pool.append(d)

if pool:
    alld = pd.concat(pool, ignore_index=True)
    report("POOLED (BTC+ETH)", alld)
    e = alld[(alld["fc_dir"] != "neutral") & (alld["realized"] != "flat") & alld["realized"].notna()].copy()
    e["contra"] = np.where(e["fc_dir"] == "up", "down", "up")
    print("\n===== 動能 vs 反向(mean-reversion) + 時間穩定度 =====")
    for seg in ["train", "test"]:
        g = e[e["seg"] == seg]
        if len(g):
            mom = (g["fc_dir"] == g["realized"]).mean()
            con_hit = (g["contra"] == g["realized"])
            lo, hi = wilson(con_hit.sum(), len(g))
            print(f"  {seg:5s}(前70/後30) n={len(g):6d} | 動能 {mom:.4f} | 反向 {con_hit.mean():.4f} "
                  f"(反向 Wilson95% [{lo:.4f}, {hi:.4f}])")
