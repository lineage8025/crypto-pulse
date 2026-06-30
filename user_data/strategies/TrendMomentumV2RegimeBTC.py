import pandas as pd
import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute


class TrendMomentumV2RegimeBTC(IStrategy):
    """
    V2(ATR×5 Chandelier) + BTC 市場層級 regime 閘（純核心版）。

    閘 = BTC/USDT 4h: close>EMA200 且 EMA200 標準化斜率(slope_norm)≥1.0。
    原理：Faber 200日線牛熊濾網 + Weinstein Stage 2(MA上升=趨勢) vs Stage1/3(MA走平=區間)。
    slope_norm=(EMA200 - EMA200[30])/ATR14，門檻 1.0 = 訊噪比 1（教科書值，非湊 2025）。
    市場層級單一閘套全標的、只擋進場（出場維持寬 Chandelier 讓贏單奔跑）。
    第一輪刻意不加 ADX/DI/遲滯等未驗證自由度。
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

        # BTC 市場層級 regime 閘（在 BTC 4h 上算，皆 causal）
        btc = self.dp.get_pair_dataframe("BTC/USDT", "4h").copy()
        btc["ema200"] = ta.EMA(btc, timeperiod=200)
        btc["atr14"] = ta.ATR(btc, timeperiod=14)
        slope_norm = (btc["ema200"] - btc["ema200"].shift(self.btc_slope_lb)) / btc["atr14"]
        btc["btc_risk_on"] = ((btc["close"] > btc["ema200"]) & (slope_norm >= self.btc_slope_min)).astype(float)

        dataframe = merge_informative_pair(
            dataframe, btc[["date", "btc_risk_on"]], "4h", "4h", ffill=True
        )
        # 同框 merge 不位移日期 → 多 lag 一根當無前視保險（regime 慢變，無傷）
        dataframe["btc_risk_on_4h"] = dataframe["btc_risk_on_4h"].shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema50"] > dataframe["ema100"])
            & qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["adx"] > 25)
            & (dataframe["macd"] > 0)
            & (dataframe["btc_risk_on_4h"] > 0.5)          # BTC 市場 regime 閘
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
