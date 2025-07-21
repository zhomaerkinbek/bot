# 1. Базовый образ с Python 3.11
FROM python:3.11-slim

# 2. Рабочая директория
WORKDIR /app

# 3. Копируем только зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Копируем весь код
COPY . .

# 5. Переменные окружения (Render задаёт свой PORT и RENDER_EXTERNAL_URL)
ENV PORT=${PORT}
ENV RENDER_EXTERNAL_URL=${RENDER_EXTERNAL_URL}
ENV BOT_TOKEN=${BOT_TOKEN}

# 6. Запуск бота
CMD ["python", "bot.py"]
