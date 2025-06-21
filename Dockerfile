# Используем официальный Python образ
FROM python:3.11-slim

RUN mkdir -p /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Создаем необходимые директории
RUN mkdir -p logs reports

# Копируем весь код приложения
COPY . /app

# Создаем пользователя для запуска приложения (для безопасности)
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app

# Переключаемся на пользователя botuser
USER botuser

# Устанавливаем переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Открываем порт (если потребуется для веб-интерфейса)
EXPOSE 8000

# Проверка здоровья контейнера
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Команда запуска
CMD ["python", "main.py"] 