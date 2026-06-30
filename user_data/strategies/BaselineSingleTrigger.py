from pandas import DataFrame
import talib.abstract as ta
from technical import qtpylib

from freqtrade.strategy import IStrategy


class BaselineSingleTrigger(IStrategy):
    """
    對照組：僅 MACD 金叉 + ADX>25 進場（去掉 TrendMomentumV1 的 EMA 多排與零軸過濾）。

    風控、出場、時框與 TrendMomentumV1 完全相同——唯一變數是進場確認的強度，
    用來量化「三重確認」相對單一觸發到底有沒有加值（A/B 對照）。
    """

    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = False

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

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ema50 僅供出場使用，使出場條件與 TrendMomentumV1 一致
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]

        dataframe["adx"] = ta.ADX(dataframe)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
                & (dataframe["adx"] > 25)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
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
