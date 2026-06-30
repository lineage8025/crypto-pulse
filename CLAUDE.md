# crypto-pulse — freqtrade 加密貨幣漲跌量化追蹤

## 專案定位
加密貨幣「漲跌量化追蹤」系統。骨幹 = **freqtrade**（crypto-native，內建 ccxt 數據 + 回測 + hyperopt + dry-run 告警 + 實盤 + FreqAI）。
v1 範圍：**BTC/USDT + ETH/USDT、現貨(spot)、只做多**。先做 dry-run 紙上告警，驗證後同一份 strategy 改 `dry_run=false` 即實盤。
與 quant-trading / SwingPulse **保持獨立**，不共用 code。

## 環境 / 執行
- 一律走 **Docker**（官方 image `freqtradeorg/freqtrade:stable` 已內建 ta-lib，不在本機裝 ta-lib）。
- 所有指令前綴：`docker compose run --rm freqtrade <cmd>`（在專案根目錄執行）。
- ⚠ 本專案**擁抱 freqtrade 指標生態**：`import talib.abstract as ta` + `from technical import qtpylib`，**不要**套用 quant-trading 的「純 pandas/numpy」原則（那條綁在舊專案）。
- ⚠ 主機 **8080 已被 moorcheh-onprem-server 佔用**，docker-compose.yml 的 `ports` 映射已註解（api_server 也已關）。要開 freqtrade Web UI 改用別的埠（如 8081）。
- ⚠ 目前 dry-run 跑 **15m**（config timeframe=15m，覆寫策略）；但回測驗證是在 **4h**，15m 尚未回測，數字未驗證。

## 結構
```
docker-compose.yml                     # 官方範本
user_data/config.json                  # dry_run / spot / BTC,ETH / Telegram
user_data/lookahead_override.json      # 僅供 lookahead-analysis 覆寫 pricing(price_side=other)
user_data/strategies/
  TrendMomentumV1.py                   # v1 主策略
  BaselineSingleTrigger.py             # A/B 對照組(驗證三重確認加值)
user_data/data/binance/               # OHLCV(feather)
```

## strategy 慣例（freqtrade v3）
`INTERFACE_VERSION = 3`；信號欄位 `enter_long` / `exit_long`（**非** buy/sell）；`can_short` 在 class 內（v1=False，**不在 config**）；方法 `populate_indicators` / `populate_entry_trend` / `populate_exit_trend`。

## v1 策略：TrendMomentumV1（多 agent 對抗式評審勝出）
- 4h；進場 AND：EMA20>50>100 + MACD 金叉 + ADX>25 + MACD>0 + volume>0
- 出場 OR：MACD 死叉 | close<EMA50；trailing(offset 8%/回吐 3%)；硬停 -10%；ROI 寬鬆只當保險
- **v1 鎖死參數、禁 hyperopt**；先驗訊號質量，不追績效

## 常用指令
```bash
docker compose run --rm freqtrade download-data --exchange binance --pairs BTC/USDT ETH/USDT --timeframes 4h --timerange 20220101-
docker compose run --rm freqtrade backtesting --strategy TrendMomentumV1 --config user_data/config.json --timerange 20220101- --breakdown month
docker compose run --rm freqtrade lookahead-analysis --strategy TrendMomentumV1 --config user_data/config.json --config user_data/lookahead_override.json --timerange 20230101-
docker compose up -d && docker compose logs -f      # dry-run 上線(需先填 .env 的 Discord webhook)
```

## v1 首輪回測發現（2022-02 ~ 2026-06，BTC/ETH 4h）
- TrendMomentumV1：77 筆、**-2.14%**、PF 0.79、勝率 32.5%
- BaselineSingleTrigger：108 筆、**-5.03%**、PF 0.66、勝率 28.7%
- 結論：三重確認**確實優於**單一觸發(過濾掉爛訊號)，但**兩者皆淨負**——此基礎 edge 在這段 BTC/ETH 期間不存在。lookahead-analysis 乾淨(無前視)。
- 含意：v1 作為「驗證 harness」成功；下一步是擴標的提升統計力、改進訊號或調風控，而非直接上實盤。

## 告警（Discord）
- 告警走 **Discord webhook**（非 Telegram）。config.json 有獨立頂層 `discord` 區塊：`enabled:true` + `webhook_url`(佔位符) + `allow_custom_messages:true` + `strategy_msg:[{"Alert":"{msg}"}]`。
- **webhook URL 從 `.env` 注入**（`DISCORD_WEBHOOK_URL`），docker-compose 用 `FREQTRADE__DISCORD__WEBHOOK_URL=${DISCORD_WEBHOOK_URL}` 覆寫 config 佔位符。secret 不進版控（`.env` 已 gitignore）。要啟用：編輯 `.env` 貼上真實 URL。
- **預設交易通知**：entry_fill / exit_fill（freqtrade 內建樣板，dry-run 照送）。
- **主動漲跌追蹤告警**：`TrendMomentumV1.populate_indicators` 內已加 `self.dp.send_msg()`，4h 收盤站上/跌破 EMA100 → 推「趨勢轉強/轉弱」。**僅 live/dry-run 觸發，backtest 為 no-op**（已回歸驗證回測不受影響）。
- 雷：`discord` 是頂層 key（非 webhook.discord）、URL 欄位是 `webhook_url`（非 url），寫錯靜默不送。Discord 無 per-exit-reason 粒度、無 silent 模式。速率限 30 req/30s/webhook。

## 路線圖
v1.1 主動漲跌告警(✅ 已加 EMA100 穿越 send_msg) → 擴低相關 alt 標的 → 克制 hyperopt → MTF → 期貨雙向做空 → FreqAI

## 文件同步規則
新增 script / 策略 / 改動結構時，**同步更新本檔與 MEMORY.md**。
