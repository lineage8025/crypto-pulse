import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import talib.abstract as ta
from technical import qtpylib
from pandas import DataFrame

from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)


class MeanRevertMaker15m(IStrategy):
    """
    15m 均值回歸 + 限價(maker)進出場。

    順 15m 的紋理(均值回歸)、用 maker 費率保住薄 edge：
    回測(近3週)毛利 PF1.49、maker~0.02% PF1.31(正)、taker0.1% PF0.92(被吃光)。
    進出場掛同側盤口頂的限價單 → 爭取 maker；停損用市價單保命。
    最大未知 = maker 限價單的真實成交率(回測假設都成交、偏樂觀)，
    故掛 Bitget dry-run 往前驗真實 fill 行為。現貨只多。
    """

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = False

    minimal_roi = {"0": 0.15}     # 高上限，正常由回中軌出場
    stoploss = -0.06              # 接刀保護
    trailing_stop = False
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 60

    # 限價進出場(爭取 maker)，停損市價(保證出場)
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

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

    # ---- 本地交易紀錄：user_data/logs/trade_journal.jsonl（僅 live/dry-run）----
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
            "session_start", "-",
            strategy=self.__class__.__name__, timeframe=self.timeframe,
            dry_run=bool(self.config.get("dry_run")), order_entry=self.order_types["entry"],
        )

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs) -> bool:
        self._journal(
            "entry", pair, when=current_time, side=side, order_type=order_type,
            rate=float(rate), amount=float(amount), stake=float(rate) * float(amount),
        )
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs) -> bool:
        entry_rate = float(trade.open_rate)
        profit_ratio = (float(rate) - entry_rate) / entry_rate if entry_rate else None
        self._journal(
            "exit", pair, when=current_time, exit_reason=exit_reason, order_type=order_type,
            rate=float(rate), amount=float(amount), entry_rate=entry_rate,
            profit_ratio=round(profit_ratio, 5) if profit_ratio is not None else None,
        )
        return True
