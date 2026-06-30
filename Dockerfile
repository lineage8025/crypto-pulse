# 把 config + 策略烤進 image，避開 Portainer git-stack 相對 bind 掛載的坑
FROM freqtradeorg/freqtrade:stable
USER root
COPY user_data/ /freqtrade/user_data/
RUN mkdir -p /freqtrade/user_data/logs /freqtrade/user_data/data \
 && chmod -R 777 /freqtrade/user_data
# 切回 ftuser 執行（freqtrade venv/PATH 綁這個 user；用 root 會 ModuleNotFound）
# 寫入權限靠上面 chmod 777 + named volume 解決
USER ftuser
