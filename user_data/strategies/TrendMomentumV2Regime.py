import pandas as pd
import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, stoploss_from_absolute


class TrendMomentumV2Regime(IStrategy):
    """
    Config1(ExitFix) + 市場 regime 過濾：只在長期多頭(close>EMA200)做多，避開熊市拖累。
    出場 = Chandelier(22, 3×ATR) 追蹤，無過敏 exit_signal，解封 ROI。4h。
    """

    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 10}
    stoploss = -0.20
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = False
    process_only_new_candles = True
    startup_candle_count = 300

    ce_window = 22
    ce_atr_mult = 3.0
    atr_period = 14

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
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
            & (dataframe["close"] > dataframe["ema200"])      # 長期多頭 regime 閘
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
        ce = df["chandelier_long"].shift(1).iloc[-1]
        if pd.isna(ce) or ce <= 0:
            return None
        return stoploss_from_absolute(ce, current_rate, is_short=False)
