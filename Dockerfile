# 把 config + 策略烤進 image，避開 Portainer git-stack 相對 bind 掛載的坑
FROM freqtradeorg/freqtrade:stable
USER root
COPY user_data/ /freqtrade/user_data/
RUN mkdir -p /freqtrade/user_data/logs /freqtrade/user_data/data \
 && chmod -R 777 /freqtrade/user_data
# 以 root 跑（NAS dry-run 容器），確保可寫 log/db
