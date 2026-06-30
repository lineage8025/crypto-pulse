# crypto-pulse MEMORY

## 專案
- crypto-pulse：freqtrade 加密貨幣漲跌量化追蹤，v1=BTC/ETH 現貨做多、dry-run 紙上告警。與 quant-trading/SwingPulse 獨立。
- 走 Docker（image 內建 ta-lib）；指標用 talib.abstract + qtpylib，不套舊專案的純 pandas 原則。

## 決策
- 用 freqtrade 取代 backtrader：一條龍涵蓋數據/回測/告警/實盤/ML。
- v1 主策略 TrendMomentumV1（EMA 多排×MACD 金叉×ADX>25, 4h）為多 agent 對抗式評審勝出方案；v1 鎖死參數、禁 hyperopt，並起 BaselineSingleTrigger 對照組。

## 發現（首輪回測 2022-02~2026-06）
- 三重確認(-2.14%, PF0.79) 優於單一觸發(-5.03%, PF0.66)，但兩者皆淨負 → 基礎 edge 在此期間 BTC/ETH 不存在。
- lookahead-analysis 無前視偏差。
- v1 驗證 harness 成功；下一步擴標的/改訊號，勿直接上實盤。

## 發現（DirProbe-v1 下一跳方向，92k 樣本離線量測）
- 動能版次根方向命中僅 ~46%（POOLED 45.9%, Wilson±0.3%），輸給 base rate 50.5%，信心值反向校準（越自信越錯）。
- 反向＝均值回歸 ~53–54%，train/test 皆樣本外顯著 >50% → 15m 次根是短週期均值回歸，非動能延續。
- 但 53–54% 方向 ≠ 會賺，需含手續費(~0.2%來回)損益回測；列為獨立 mean-reversion 新策略去驗。
- 已把 TrendMomentumV1 的 use_forecast_filter 關閉（動能預測拿來當順勢進場是反效果）；預測器仍持續 live 記錄。
- 離線腳本：user_data/analyze_forecast_history.py（容器內 --entrypoint python 跑）。

## 告警
- 走 Discord webhook（非 Telegram）。config.json 有 discord 區塊，webhook URL 由 .env 的 DISCORD_WEBHOOK_URL 注入（gitignore）。
- 交易通知 entry_fill/exit_fill 內建；主動漲跌告警已加（TrendMomentumV1 收盤穿越 EMA100 send_msg，backtest no-op）。

## 待辦
- 編輯 .env 貼上真實 Discord webhook URL 才會實際推播（目前是佔位符）。
- docker-compose command 已改為 --strategy TrendMomentumV1（原範本是 SampleStrategy）。
