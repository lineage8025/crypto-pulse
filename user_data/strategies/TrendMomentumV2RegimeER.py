import pandas as pd
import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, stoploss_from_absolute


class TrendMomentumV2RegimeER(IStrategy):
    """
    CE50(ATR×5 Chandelier) + Kaufman 效率比(ER) regime 濾網。

    OOS 發現：底層趨勢 edge regime 依賴，2025 震盪盤被洗(-17%)。
    ER = |close - close[n]| / Σ|close.diff()|(n)，高=趨勢、低=震盪。
    只在 ER>門檻(趨勢明確)才進場，避開震盪期。門檻用教科書值，兩期都驗以防過擬合。
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
    er_window = 10
    er_min = 0.30

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
        # Kaufman 效率比：淨移動 / 總路徑（高=趨勢，低=震盪）
        change = (dataframe["close"] - dataframe["close"].shift(self.er_window)).abs()
        volatility = dataframe["close"].diff().abs().rolling(self.er_window).sum()
        dataframe["er"] = change / volatility
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema50"] > dataframe["ema100"])
            & qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["adx"] > 25)
            & (dataframe["macd"] > 0)
            & (dataframe["er"] > self.er_min)          # regime 濾網：只在趨勢明確時進
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
