# crypto-pulse 部署到 Synology DS423+ (Portainer)

NAS 只跑 **live dry-run bot**（24/7、輕量）。回測/hyperopt 仍在本機 28 核跑。

## 1. 在 NAS 建資料夾
File Station 或 SSH 建：`/volume1/docker/crypto-pulse/user_data/`
底下需有：`strategies/`、`logs/`、`data/`（空的即可，data live 會自己抓）

## 2. 把檔案放上 NAS（只要這些，不必搬歷史資料）
從本機 `/home/michael/crypto-pulse/user_data/` 複製到 NAS 對應位置：
- `config_bitget_btc15m.json`
- `strategies/MeanRevertMakerMTF.py`（這支自包含，不依賴其他策略檔）
> live dry-run 會自己向 Bitget 抓近期 K 線，所以 `data/` 不用搬（省幾百 MB）。

## 3. 權限（Synology 常見坑）
容器內 freqtrade 以 uid 1000 (ftuser) 執行，要能寫 `logs/` 與 sqlite db。
若啟動報權限錯，對 `user_data` 給寫入權限：
```bash
# SSH 進 NAS
chmod -R 777 /volume1/docker/crypto-pulse/user_data
```

## 4. Portainer 部署
Portainer → **Stacks → Add stack** → 命名 `crypto-pulse` → 貼上 `docker-compose.nas.yml` 內容 → **Deploy the stack**
- 會拉 image（~1.3GB，一次性）後啟動。
- 路徑若不是 `/volume1/docker/...`，改 compose 裡 volume 左半。

## 5. 確認
Portainer → Containers → `crypto-pulse` → Logs，應看到：
- `Using Exchange "Bitget"`、`Dry run is enabled`
- `Using resolved strategy MeanRevertMakerMTF`、`timeframe: 15m`
- `Changing state to: RUNNING`、無 error

## 6. 觀察
交易紀錄在 NAS 的 `user_data/logs/trade_journal.jsonl`（File Station 直接看）。

## 上實盤前（之後再做，非現在）
- config 改 `dry_run: false` + 填 Bitget API key（建議 .env 注入、別寫死）
- 開 `stoploss_on_exchange: true`（讓交易所端掛停損，bot/NAS 掛了也保命）
- 確認 NAS 對外網路穩定、設容器自動更新策略
