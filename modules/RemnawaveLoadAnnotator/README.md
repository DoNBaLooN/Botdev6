# Remnawave Load Annotator

Модуль автоматически обновляет ремарки серверов в панели Remnawave в зависимости от текущей загрузки, полученной из Node Exporter. Он добавляет кнопку в админ‑панель бота для просмотра доступных хостов и запускает фонового воркера, который периодически опрашивает все настроенные ноды.

## Предварительные требования

1. **Установка и настройка Netbird** для связывания серверов. Установите Netbird на сервере бота и на всех нодах (панель Remnawave не требуется подключать). Инструкция: [https://wiki.egam.es/ru/configuration/netbird/](https://wiki.egam.es/ru/configuration/netbird/).
2. **Установка Node Exporter** на каждой ноде.

## 🚀 Установка Node Exporter (одной командой)

```bash
mkdir -p /opt/monitoring/nodeexporter && cd /opt/monitoring/nodeexporter && \
wget -q https://github.com/prometheus/node_exporter/releases/download/v1.9.1/node_exporter-1.9.1.linux-amd64.tar.gz && \
tar -xzf node_exporter-1.9.1.linux-amd64.tar.gz && \
mv node_exporter-1.9.1.linux-amd64/node_exporter /opt/monitoring/nodeexporter/ && \
chmod +x /opt/monitoring/nodeexporter/node_exporter && \
rm -rf node_exporter-1.9.1.linux-amd64* && \
cat <<'SERVICE' > /etc/systemd/system/nodeexporter.service
[Unit]
Description=Node Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=root
Group=root
Type=simple
ExecStart=/opt/monitoring/nodeexporter/node_exporter --web.listen-address=:9100
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload && systemctl enable nodeexporter && systemctl start nodeexporter && \
echo "✅ Node Exporter установлен и запущен. Теперь добавьте правило безопасности ниже 👇"
```

## 🔐 Настройка доступа

Ограничьте доступ к `9100/tcp` на каждой ноде

### 1. Узнайте IP Netbird на сервере бота

```bash
netbird status | grep "NetBird IP"
```

Пример вывода:

```
NetBird IP: 100.107.3.133/16
```

Используйте IP без /16 — `100.107.3.133`.

### 2. Если используется UFW добавьте ip netbird сервера бота в каждой ноде

```bash
sudo ufw allow from 100.107.3.133 to any port 9100 proto tcp
sudo ufw status numbered
```

### 3. Если используется iptables добавьте ip netbird сервера бота в каждой ноде

```bash
sudo iptables -A INPUT -p tcp -s 100.107.3.133 --dport 9100 -j ACCEPT
sudo iptables-save > /etc/iptables/rules.v4
```

### 🔍 Проверка на сервере бота

```bash
curl http://ip_ноды:9100/metrics | head
```

Если видите строки типа:

```
# HELP go_gc_duration_seconds ...
```

— значит Node Exporter работает.

## ⚙️ Настройка Remnawave Load Annotator


1. **Получите UUID хостов.**

   * Добавьте модуль в папку modules и перезапустите бота.
   * В админ‑панели бота нажмите **«📋 Хосты Remnawave»**.
   * Скопируйте UUID хостов, которые нужно мониторить.

2. **Добавьте ноды в `settings.py`.**
   Пример:

   ```python
   NODES = (
       {
           "title": "🇩🇪 Германия", # Тут вставить название хоста как у вас в панели Remnawave
           "endpoint": "100.107.3.15:9100",  # IP Netbird + порт Node Exporter
           "uuid": "f964a24b-28c4-4f5e-bd90-483302cab127",  # UUID из бота
       },
       {
           "title": "🇸🇪 Швеция",
           "endpoint": "100.107.4.22:9100",
           "uuid": "b281d60d-24b5-48e2-80b3-1250a937eafe",
       },
   )
   ```

3. **Проверьте работу.**
   После настройки перезапустите модуль. После запуска, модуль каждые `INTERVAL_SEC` секунд собирает метрики. В логах появятся строки:

   ```
   [RemnawaveLoadAnnotator] Обновлён 🇩🇪 Германия (...): 🟢12%
   ```

   В панели Remnawave ремарки хостов обновятся с процентом загрузки CPU.

## ✅ Проверка

* `systemctl status nodeexporter` — убедитесь, что сервис активен.
* В логах ищите `[RemnawaveLoadAnnotator] Обновлён ...`.
* В панели Remnawave ремарки должны показывать актуальную загрузку CPU.
