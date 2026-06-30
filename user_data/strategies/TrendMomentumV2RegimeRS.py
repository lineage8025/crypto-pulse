import pandas as pd
import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute


class TrendMomentumV2RegimeRS(IStrategy):
    """
    regime 閘 + 相對強度(RS vs BTC)選股層。
    在 BTC 市場 regime 放行的前提下，只做「相對 BTC 跑贏」(RS≥1)的標的，
    過濾落後者、把資金集中在強勢標的（Minervini RS 精神的可實作代理）。
    RS = (標的 close/close[lb]) / (BTC close/close[lb])。4h，現貨只多，出場純 Chandelier(×5)。
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
    btc_slope_lb = 30
    btc_slope_min = 1.0
    rs_lb = 60                 # RS 回看 60 根 4h ≈ 10 天
    rs_min = 1.0              # 只做相對 BTC 跑贏（≥1）

    def informative_pairs(self):
        return [("BTC/USDT", "4h")]

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

        btc = self.dp.get_pair_dataframe("BTC/USDT", "4h").copy()
        btc["ema200"] = ta.EMA(btc, timeperiod=200)
        btc["atr14"] = ta.ATR(btc, timeperiod=14)
        slope_norm = (btc["ema200"] - btc["ema200"].shift(self.btc_slope_lb)) / btc["atr14"]
        btc["btc_risk_on"] = ((btc["close"] > btc["ema200"]) & (slope_norm >= self.btc_slope_min)).astype(float)
        btc["btc_roc"] = btc["close"] / btc["close"].shift(self.rs_lb)

        dataframe = merge_informative_pair(
            dataframe, btc[["date", "btc_risk_on", "btc_roc"]], "4h", "4h", ffill=True
        )
        dataframe["btc_risk_on_4h"] = dataframe["btc_risk_on_4h"].shift(1)
        dataframe["btc_roc_4h"] = dataframe["btc_roc_4h"].shift(1)

        pair_roc = dataframe["close"] / dataframe["close"].shift(self.rs_lb)
        dataframe["rs"] = pair_roc / dataframe["btc_roc_4h"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema50"] > dataframe["ema100"])
            & qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["adx"] > 25)
            & (dataframe["macd"] > 0)
            & (dataframe["btc_risk_on_4h"] > 0.5)          # regime 閘
            & (dataframe["rs"] >= self.rs_min)             # RS：相對 BTC 跑贏
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
