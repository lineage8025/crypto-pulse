import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class MeanRevert4h(IStrategy):
    """
    4h 均值回歸（買超賣反彈，現貨只多）—— 用來驗證「震盪盤均值回歸到底賺不賺」。
    進場：RSI(14)<30 且 close 跌破布林下軌(20,2)。
    出場：RSI 回到 >50 或 close 站回中軌（回歸完成）；ATR/固定停損保護接刀風險。
    若此策略在 2025 震盪盤為正 → regime 切換雙策略成立；否則震盪盤最佳解是不交易。
    """

    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 0.15}      # 上限保險，正常由 exit_signal 先出
    stoploss = -0.08               # 接刀保護
    trailing_stop = False
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 60

    rsi_buy = 30
    rsi_exit = 50

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lower"] = bb["lower"]
        dataframe["bb_mid"] = bb["mid"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["rsi"] < self.rsi_buy)
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
