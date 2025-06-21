# Docker Развертывание Криптовалютного Торгового Бота

Этот документ описывает, как развернуть торгового бота с использованием Docker.

## 📋 Предварительные требования

- Docker (версия 20.10+)
- Docker Compose (версия 1.28+)
- Файл `.env` с необходимыми переменными окружения

## 🔧 Подготовка к развертыванию

### 1. Создание .env файла

Создайте файл `.env` в корневой директории проекта:

```bash
# API ключи Bitget
API_KEY=ваш_api_ключ_bitget
SECRET_KEY=ваш_секретный_ключ_bitget
PASSPHRASE=ваш_пароль_bitget

# Telegram бот
TELEGRAM_BOT_TOKEN=токен_вашего_телеграм_бота
TARGET_CHAT_ID=id_чата_для_отправки_уведомлений
```

### 2. Подготовка директорий

Убедитесь, что директории `logs` и `reports` существуют:

```bash
mkdir -p logs reports
```

## 🚀 Запуск с Docker Compose (Рекомендуется)

### Сборка и запуск

```bash
# Сборка образа и запуск контейнера
docker-compose up -d --build

# Просмотр логов в реальном времени
docker-compose logs -f crypto-bot

# Проверка статуса
docker-compose ps
```

### Управление контейнером

```bash
# Остановка
docker-compose down

# Перезапуск
docker-compose restart

# Обновление кода и перезапуск
docker-compose down
docker-compose up -d --build
```

## 🐋 Запуск с Docker (без Compose)

### Сборка образа

```bash
docker build -t crypto-trading-bot .
```

### Запуск контейнера

```bash
docker run -d \
  --name crypto-bot \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/reports:/app/reports \
  crypto-trading-bot
```

### Управление контейнером

```bash
# Просмотр логов
docker logs -f crypto-bot

# Остановка
docker stop crypto-bot

# Удаление
docker rm crypto-bot

# Перезапуск
docker restart crypto-bot
```

## 📊 Мониторинг и логи

### Просмотр логов бота

```bash
# Docker Compose
docker-compose logs -f crypto-bot

# Docker
docker logs -f crypto-bot

# Файлы логов (если смонтированы)
tail -f logs/bot.log
tail -f logs/strategy_btcstrategy.log
tail -f logs/strategy_ethstrategy.log
```

### Проверка здоровья контейнера

```bash
# Docker Compose
docker-compose ps

# Docker
docker ps
docker inspect crypto-bot --format='{{.State.Health.Status}}'
```

## 🔧 Настройка ресурсов

Лимиты ресурсов можно изменить в `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      memory: 1G        # Увеличить лимит памяти
      cpus: '1.0'       # Увеличить лимит CPU
    reservations:
      memory: 512M
      cpus: '0.5'
```

## 🐛 Отладка и устранение неполадок

### Подключение к контейнеру

```bash
# Docker Compose
docker-compose exec crypto-bot bash

# Docker
docker exec -it crypto-bot bash
```

### Проверка переменных окружения

```bash
docker-compose exec crypto-bot env | grep -E "(API_KEY|TELEGRAM)"
```

### Пересборка без кэша

```bash
# Docker Compose
docker-compose build --no-cache

# Docker
docker build --no-cache -t crypto-trading-bot .
```

### Очистка Docker ресурсов

```bash
# Удаление неиспользуемых образов
docker image prune -f

# Удаление всех остановленных контейнеров
docker container prune -f

# Общая очистка системы
docker system prune -f
```

## 📈 Резервное копирование данных

### Создание бэкапа логов и отчетов

```bash
# Создание архива
tar -czf backup-$(date +%Y%m%d).tar.gz logs/ reports/

# Копирование из контейнера (если не используются volume)
docker cp crypto-bot:/app/logs ./logs-backup
docker cp crypto-bot:/app/reports ./reports-backup
```

## 🚀 Автоматическое развертывание

### Пример скрипта для автоматического обновления

```bash
#!/bin/bash
# update-bot.sh

set -e

echo "Обновление торгового бота..."

# Остановка текущего контейнера
docker-compose down

# Обновление кода (если используется Git)
git pull origin main

# Пересборка и запуск
docker-compose up -d --build

echo "Бот успешно обновлен и запущен!"

# Проверка логов
sleep 10
docker-compose logs --tail=20 crypto-bot
```

### Создание systemd сервиса (Linux)

```bash
sudo tee /etc/systemd/system/crypto-bot.service > /dev/null <<EOF
[Unit]
Description=Crypto Trading Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/path/to/your/bot
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable crypto-bot
sudo systemctl start crypto-bot
```

## ⚠️ Безопасность

1. **Никогда не включайте `.env` файл в образ Docker**
2. **Используйте секреты Docker для продакшена:**

```yaml
services:
  crypto-bot:
    secrets:
      - api_key
      - secret_key

secrets:
  api_key:
    file: ./secrets/api_key.txt
  secret_key:
    file: ./secrets/secret_key.txt
```

3. **Регулярно обновляйте базовый образ:**

```bash
docker pull python:3.11-slim
docker-compose build --no-cache
```

## 📞 Поддержка

При возникновении проблем проверьте:
1. Корректность файла `.env`
2. Доступность API Bitget
3. Логи контейнера
4. Статус сетевых соединений 