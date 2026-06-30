import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy, merge_informative_pair

logger = logging.getLogger(__name__)


class MeanRevertMakerMTF(IStrategy):
    """
    跨週期順勢回調 + 限價(maker) —— 15m 進場、1H 趨勢過濾。

    大週期(1H 200EMA)定方向：只在 1H 多頭時，買 15m 超賣回調(RSI<30 且跌破布林下軌)。
    = 「順大勢、吃小級別插針」，避開純 15m MR 在趨勢爆發被帶走、與純 15m 動能在盤整雙巴。
    限價進出場爭取 maker 費率(薄 edge 的命脈)；停損市價保命。現貨只多。
    時段過濾做成可選 A/B 變數(預設關，避免一次疊太多濾網無法歸因)。
    """

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = False

    minimal_roi = {"0": 0.15}
    stoploss = -0.06
    trailing_stop = False
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 850          # 1H EMA200 需 ~800 根 15m 暖機

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    rsi_buy = 30
    rsi_exit = 50
    inf_tf = "1h"

    # A/B 開關
    use_trend_filter = True            # 1H 趨勢過濾(核心 MTF 升級)
    use_session_filter = False         # 時段過濾(預設關，當 A/B 變數)
    session_start_utc = 12             # 只在 UTC>=12(避亞洲死魚盤、抓歐美時段)
    session_end_utc = 24

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(p, self.inf_tf) for p in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lower"] = bb["lower"]
        dataframe["bb_mid"] = bb["mid"]

        # 1H 趨勢過濾器
        inf = self.dp.get_pair_dataframe(metadata["pair"], self.inf_tf)
        inf["ema200"] = ta.EMA(inf, timeperiod=200)
        inf["trend_up"] = (inf["close"] > inf["ema200"]).astype(float)
        dataframe = merge_informative_pair(
            dataframe, inf[["date", "trend_up"]], self.timeframe, self.inf_tf, ffill=True
        )

        dataframe["hour"] = dataframe["date"].dt.hour
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (
            (dataframe["rsi"] < self.rsi_buy)
            & (dataframe["close"] < dataframe["bb_lower"])
            & (dataframe["volume"] > 0)
        )
        if self.use_trend_filter:
            cond &= dataframe[f"trend_up_{self.inf_tf}"] > 0.5
        if self.use_session_filter:
            cond &= (dataframe["hour"] >= self.session_start_utc) & (dataframe["hour"] < self.session_end_utc)
        dataframe.loc[cond, "enter_long"] = 1
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

    # ---- 本地交易紀錄 ----
    def _journal(self, event: str, pair: str, when=None, **data) -> None:
        if self.dp.runmode.value not in ("live", "dry_run"):
            return
        ts = when if when is not None else datetime.now(timezone.utc)
        record = {"time": str(ts), "event": event, "pair": pair, **data}
        path = Path(self.config["user_data_dir"]) / "logs" / "trade_journal.jsonl"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning("trade_journal write failed: %s", exc)

    def bot_start(self, **kwargs) -> None:
        self._journal(
            "session_start", "-", strategy=self.__class__.__name__, timeframe=self.timeframe,
            trend_filter=self.use_trend_filter, session_filter=self.use_session_filter,
            dry_run=bool(self.config.get("dry_run")),
        )

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs) -> bool:
        self._journal("entry", pair, when=current_time, side=side, order_type=order_type,
                      rate=float(rate), amount=float(amount), stake=float(rate) * float(amount))
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs) -> bool:
        entry_rate = float(trade.open_rate)
        pr = (float(rate) - entry_rate) / entry_rate if entry_rate else None
        self._journal("exit", pair, when=current_time, exit_reason=exit_reason, order_type=order_type,
                      rate=float(rate), entry_rate=entry_rate,
                      profit_ratio=round(pr, 5) if pr is not None else None)
        return True


class MRM_NoFilter(MeanRevertMakerMTF):
    use_trend_filter = False
    use_session_filter = False


class MRM_TrendSession(MeanRevertMakerMTF):
    use_trend_filter = True
    use_session_filter = True
