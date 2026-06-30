import numpy as np
import talib
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class MeanRevertV1(IStrategy):
    """
    15m 短週期均值回歸（現貨只做多側 ＝ 跌多搶反彈）。

    源於 DirProbe 離線量測（92k 樣本）：動能型次根方向命中 ~46%(反指) → 反向 ~54%。
    本策略在「強下跌動能」後做多、持約 1 根 15m，含手續費回測驗證 54% 方向命中能否轉成獲利。

    出場用「每根都掛 exit_long」的向量化機制：進場(訊號 t→t+1 open 成交)後，
    t+1 即見出場訊號 → t+2 open 平倉 ＝ 穩定持有 1 根，可靠且不依賴 custom_exit。
    roi/stoploss 放寬只當保險，純測「1 根反彈」的扣費後淨值。
    """

    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = False

    minimal_roi = {"0": 10}      # 形同停用
    stoploss = -0.99             # 形同停用
    trailing_stop = False
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 120

    # DirProbe 訊號參數（與量測一致）+ 進場門檻
    fc_slope_window = 8
    fc_vol_window = 96
    fc_scale = 2.0
    entry_score = -0.10          # fc_score ≤ 此（強下跌動能）→ 搶反彈做多

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        logc = np.log(dataframe["close"])
        slope = talib.LINEARREG_SLOPE(logc.values, timeperiod=self.fc_slope_window)
        vol = logc.diff().rolling(self.fc_vol_window).std().values
        mom_s = np.tanh((slope / (vol + 1e-9)) / self.fc_scale)
        adx = ta.ADX(dataframe)
        regime = ((adx - 20.0) / 15.0).clip(0.0, 1.0)
        dataframe["fc_score"] = (mom_s * (0.4 + 0.6 * regime)).clip(-1, 1).fillna(0.0)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["fc_score"] <= self.entry_score) & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 每根都掛出場 → 進場後恆持有 1 根即平倉
        dataframe.loc[dataframe["volume"] > 0, "exit_long"] = 1
        return dataframe
