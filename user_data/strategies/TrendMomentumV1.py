import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import talib
import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)


class TrendMomentumV1(IStrategy):
    """
    v1 趨勢動能追隨：EMA 多排 × MACD 金叉 × ADX>25，4h，現貨做多。

    多 agent 對抗式評審勝出方案：三視角總分最高、最簡單、回測零摩擦。
    v1 參數一律鎖死、禁止 hyperopt；先驗證「漲跌訊號管不管用」，不追求績效。
    「跌」的方向在現貨無法做空，靠出場 / 不進場 / dry-run 內建告警體現。
    """

    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = False

    # 風控起手值（v1 鎖死，寬鬆 ROI 只當保險，靠 trailing 讓利潤奔跑）
    minimal_roi = {
        "0": 0.30,
        "1440": 0.15,
        "2880": 0.06,
        "5760": 0,
    }
    stoploss = -0.10

    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.08
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True
    startup_candle_count = 300

    # ---- DirProbe-v1 下一跳方向預測參數（可調）----
    fc_slope_window = 8         # log-close 線性回歸斜率窗 K
    fc_vol_window = 96          # log-return 波動標準化窗 NVOL
    fc_scale = 2.0             # tanh 飽和尺度 S
    fc_vol_sma_window = 20      # 量能均線窗 VOLW
    fc_neutral_band = 0.10     # 中性死區 BAND
    # 離線量測(92k 樣本)證實動能版次根命中僅 ~46%(反指)，故過濾關閉、不拿來當順勢進場；
    # 預測器仍持續記錄以驗證 live。均值回歸(~54%)另立新策略正式驗證。
    use_forecast_filter = False   # True=預測方向當進場過濾；False=只記錄不影響交易
    forecast_min_conf = 0.0       # 進場所需最低信心（0=只看方向）

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]

        dataframe["adx"] = ta.ADX(dataframe)

        # ---- DirProbe-v1：下一根方向預測（純 ≤t、全 FIR、無前視）----
        logc = np.log(dataframe["close"])
        slope = talib.LINEARREG_SLOPE(logc.values, timeperiod=self.fc_slope_window)
        vol = logc.diff().rolling(self.fc_vol_window).std().values
        dataframe["mom_z"] = slope / (vol + 1e-9)
        mom_s = np.tanh(dataframe["mom_z"] / self.fc_scale)
        dataframe["regime"] = ((dataframe["adx"] - 20.0) / 15.0).clip(0.0, 1.0)

        rng = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        body = (dataframe["close"] - dataframe["open"]) / rng
        clv = (2 * dataframe["close"] - dataframe["high"] - dataframe["low"]) / rng
        vsma = dataframe["volume"].rolling(self.fc_vol_sma_window, min_periods=self.fc_vol_sma_window).mean()
        vconf = ((dataframe["volume"] / vsma).clip(0.5, 2.0) - 0.5) / 1.5
        dataframe["micro_s"] = ((0.5 * body + 0.5 * clv) * vconf).fillna(0.0)

        dataframe["fc_score"] = (mom_s * (0.4 + 0.6 * dataframe["regime"])).clip(-1, 1).fillna(0.0)
        dataframe["fc_dir"] = np.select(
            [dataframe["fc_score"] > self.fc_neutral_band, dataframe["fc_score"] < -self.fc_neutral_band],
            ["up", "down"], default="neutral",
        )
        agree = (np.sign(dataframe["fc_score"]) == np.sign(dataframe["micro_s"])) & (dataframe["micro_s"] != 0)
        dataframe["fc_conf"] = (dataframe["fc_score"].abs() * np.where(agree, 1.0, 0.6)).clip(0, 1).fillna(0.0)
        dataframe.loc[dataframe["fc_dir"] == "neutral", "fc_conf"] = 0.0

        # 主動告警 + 預測紀錄（僅 dry-run/live；backtest 為 no-op，不影響回測）
        if self.dp.runmode.value in ("live", "dry_run") and len(dataframe) > 1:
            last = dataframe.iloc[-1]
            if qtpylib.crossed_above(dataframe["close"], dataframe["ema100"]).iloc[-1]:
                self.dp.send_msg(
                    f"📈 [{metadata['pair']}] 站上 EMA100，趨勢轉強 "
                    f"close={last['close']:.2f} @ {last['date']:%Y-%m-%d %H:%M}"
                )
                self._journal("trend_flip_up", metadata["pair"], when=last["date"], close=float(last["close"]))
            elif qtpylib.crossed_below(dataframe["close"], dataframe["ema100"]).iloc[-1]:
                self.dp.send_msg(
                    f"📉 [{metadata['pair']}] 跌破 EMA100，趨勢轉弱 "
                    f"close={last['close']:.2f} @ {last['date']:%Y-%m-%d %H:%M}"
                )
                self._journal("trend_flip_down", metadata["pair"], when=last["date"], close=float(last["close"]))

            # 記錄本根對「下一根」的方向預測
            self._journal(
                "forecast", metadata["pair"], when=last["date"],
                fc_dir=str(last["fc_dir"]),
                fc_conf=round(float(last["fc_conf"]), 4),
                fc_score=round(float(last["fc_score"]), 4),
                mom_z=round(float(last["mom_z"]), 4) if pd.notna(last["mom_z"]) else None,
                regime=round(float(last["regime"]), 3),
                micro_s=round(float(last["micro_s"]), 4),
                adx=round(float(last["adx"]), 2) if pd.notna(last["adx"]) else None,
                close=float(last["close"]),
            )
            # 對「上一根」的預測揭曉比對（realized 只在此現算，不寫成 dataframe 欄位）
            prev = dataframe.iloc[-2]
            gap_ok = (last["date"] - prev["date"]) == pd.Timedelta(self.timeframe)
            if gap_ok and str(prev["fc_dir"]) != "neutral":
                if last["close"] > prev["close"]:
                    realized = "up"
                elif last["close"] < prev["close"]:
                    realized = "down"
                else:
                    realized = "flat"
                self._journal(
                    "forecast_eval", metadata["pair"], when=last["date"],
                    forecast_time=str(prev["date"]),
                    predicted=str(prev["fc_dir"]), realized=realized,
                    hit=int(str(prev["fc_dir"]) == realized),
                    conf=round(float(prev["fc_conf"]), 4),
                    adx_at_forecast=round(float(prev["adx"]), 2) if pd.notna(prev["adx"]) else None,
                    regime_at_forecast=round(float(prev["regime"]), 3),
                    gap_ok=bool(gap_ok),
                )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = (
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema50"] > dataframe["ema100"])
            & qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["adx"] > 25)
            & (dataframe["macd"] > 0)
            & (dataframe["volume"] > 0)
        )
        if self.use_forecast_filter:
            # DirProbe-v1 當順勢過濾：只在預測下一根偏多且信心達門檻才進場
            conditions &= (dataframe["fc_dir"] == "up") & (dataframe["fc_conf"] >= self.forecast_min_conf)
        dataframe.loc[conditions, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (
                    qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"])
                    | (dataframe["close"] < dataframe["ema50"])
                )
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1
        return dataframe

    # ---- 本地交易紀錄：JSONL，寫到 user_data/logs/trade_journal.jsonl（僅 live/dry-run）----
    def _journal(self, event: str, pair: str, when=None, **data) -> None:
        if self.dp.runmode.value not in ("live", "dry_run"):
            return
        ts = when if when is not None else datetime.now(timezone.utc)
        record = {"time": str(ts), "event": event, "pair": pair, **data}
        path = Path(self.config["user_data_dir"]) / "logs" / "trade_journal.jsonl"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning("trade_journal write failed: %s", exc)

    def bot_start(self, **kwargs) -> None:
        self._journal(
            "session_start", "-",
            strategy=self.__class__.__name__,
            timeframe=self.timeframe,
            dry_run=bool(self.config.get("dry_run")),
        )

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs) -> bool:
        self._journal(
            "entry", pair, when=current_time, side=side,
            rate=float(rate), amount=float(amount), stake=float(rate) * float(amount),
            order_type=order_type, entry_tag=entry_tag,
        )
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs) -> bool:
        entry_rate = float(trade.open_rate)
        profit_ratio = (float(rate) - entry_rate) / entry_rate if entry_rate else None
        self._journal(
            "exit", pair, when=current_time, exit_reason=exit_reason,
            rate=float(rate), amount=float(amount), entry_rate=entry_rate,
            profit_ratio=round(profit_ratio, 5) if profit_ratio is not None else None,
        )
        return True
