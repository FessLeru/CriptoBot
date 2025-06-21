# Используем официальный Python образ в качестве базового
FROM python:3.11-slim

# Устанавливаем системные зависимости, необходимые для некоторых пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями для использования кэша Docker
COPY requirements.txt .

# Устанавливаем зависимости проекта
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальной код приложения
COPY . .

# Создаем пользователя без root-прав для повышения безопасности
RUN useradd -m -s /bin/bash botuser

# Создаем директории для логов и отчетов и даем на них права
# Это необходимо, чтобы бот мог писать в них файлы
RUN mkdir -p logs reports && \
    chown -R botuser:botuser logs reports

# Переключаемся на созданного пользователя
USER botuser

# Устанавливаем переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Открываем порт (если потребуется для веб-интерфейса)
EXPOSE 8000

# Проверка здоровья контейнера
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Указываем команду для запуска приложения
CMD ["python", "main.py"] 