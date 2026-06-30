import pandas as pd
import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, stoploss_from_absolute


class TrendMomentumV2RegimeVol(IStrategy):
    """
    CE50 + ATR Volatility-Expansion Ratio gate ("ATR-VER").
    vol_ratio = ATR(14) / SMA(ATR(14), 100). Gate entries on vol_ratio > 1.0.
    Per-pair. Threshold 1.0 is a definitional boundary (a priori, not tuned).
    """

    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 10}
    stoploss = -0.30
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = False
    process_only_new_candles = True
    startup_candle_count = 300

    ce_window = 22
    ce_atr_mult = 5.0
    atr_period = 14
    vol_base_window = 100
    vol_min = 1.0

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
        dataframe["atr_base"] = dataframe["atr"].rolling(self.vol_base_window).mean()
        dataframe["vol_ratio"] = dataframe["atr"] / dataframe["atr_base"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema50"] > dataframe["ema100"])
            & qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["adx"] > 25)
            & (dataframe["macd"] > 0)
            & (dataframe["vol_ratio"] > self.vol_min)
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
