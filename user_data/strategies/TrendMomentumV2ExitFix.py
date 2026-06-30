import pandas as pd
import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, stoploss_from_absolute


class TrendMomentumV2ExitFix(IStrategy):
    """
    Config 1 — 純出場端修正（診斷基準）。

    診斷（來自 baseline 4h 回測數據）：88% 出場(68/77)走 exit_signal(MACD死叉|close<EMA50)，
    那群勝率僅 25%、淨 -6.25% — 這才是壓死贏單的元兇；minimal_roi=0.30 從未綁定(max win +9.42%)。
    本版只動出場端：移除過敏 exit_signal、解封 ROI、改用 Chandelier(22, 3×ATR) 追蹤停讓贏單奔跑。
    進場完全沿用 v1，4h，鎖參禁 hyperopt。
    """

    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 10}          # 解封贏單（實為 no-op，僅確保不封頂）
    stoploss = -0.20                 # 災難地板，平時由 Chandelier 更緊優先
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = False          # 移除過敏訊號出場，純靠 Chandelier 追蹤
    process_only_new_candles = True
    startup_candle_count = 300

    ce_window = 22
    ce_atr_mult = 3.0
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
        hh = dataframe["high"].rolling(self.ce_window).max()
        dataframe["chandelier_long"] = hh - self.ce_atr_mult * dataframe["atr"]
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
        return dataframe

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or len(df) < 2:
            return None
        ce = df["chandelier_long"].shift(1).iloc[-1]   # 用上一根已收值，防盤中前視
        if pd.isna(ce) or ce <= 0:
            return None
        return stoploss_from_absolute(ce, current_rate, is_short=False)
