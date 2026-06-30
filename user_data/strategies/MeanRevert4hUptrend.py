import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class MeanRevert4hUptrend(IStrategy):
    """
    MeanRevert4h + 多頭濾網(close>EMA200)：只在上升趨勢中買超賣回踩，避開熊市接刀。
    這是教科書「buy the dip in uptrend」版，用來確認改良後的均值回歸能否在震盪盤賺。
    """

    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 0.15}
    stoploss = -0.08
    trailing_stop = False
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 260

    rsi_buy = 30
    rsi_exit = 50

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lower"] = bb["lower"]
        dataframe["bb_mid"] = bb["mid"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["ema200"])      # 只在多頭中買跌
            & (dataframe["rsi"] < self.rsi_buy)
            & (dataframe["close"] < dataframe["bb_lower"])
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["rsi"] > self.rsi_exit)
                | (dataframe["close"] > dataframe["bb_mid"])
            )
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
