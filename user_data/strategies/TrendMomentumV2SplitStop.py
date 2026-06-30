import pandas as pd
import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, stoploss_from_absolute


class TrendMomentumV2SplitStop(IStrategy):
    """
    Config 2 — 拆停 + 保本 + 寬追蹤（盈虧比主力）。

    1.5×ATR 緊初始停（縮小每筆 R）→ 獲利達 1R 後把停損移到成本+緩衝（鎖不賠）
    → 之後改 3×ATR Chandelier 寬追蹤（放大贏單）。出場只留 close<EMA100（移除過敏死叉/EMA50）。
    進場沿用 v1，4h，鎖參禁 hyperopt。
    """

    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 100}         # 停用 ROI
    stoploss = -0.15                 # 災難地板
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 300

    sl_atr_mult = 1.5                # 初始停 = 1.5×ATR
    trail_atr_mult = 3.0             # 達 1R 後 = 3×ATR 追蹤
    be_buffer = 0.003               # 保本緩衝
    be_trigger_R = 1.0               # 獲利達幾 R 後切換保本+追蹤
    atr_period = 14

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema50"] > dataframe["ema100"])
            & qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["adx"] > 25)
            & (dataframe["macd"] > 0)
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["ema100"]) & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or len(df) < 2:
            return None
        atr_now = df["atr"].shift(1).iloc[-1]
        ent = df.loc[df["date"] < trade.open_date_utc]
        if len(ent) == 0 or pd.isna(atr_now) or atr_now <= 0:
            return None
        atr_entry = ent["atr"].iloc[-1]
        if pd.isna(atr_entry) or atr_entry <= 0:
            return None
        open_rate = trade.open_rate
        r0 = self.sl_atr_mult * atr_entry / open_rate     # 初始風險(比例)
        if current_profit < self.be_trigger_R * r0:
            stop_price = open_rate - self.sl_atr_mult * atr_entry
        else:
            stop_price = max(open_rate * (1 + self.be_buffer),
                             trade.max_rate - self.trail_atr_mult * atr_now)
        return stoploss_from_absolute(stop_price, current_rate, is_short=False)
