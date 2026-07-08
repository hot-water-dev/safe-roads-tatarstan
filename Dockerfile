# Официальный образ Python
FROM python:3.11-slim

# Рабочая директория
WORKDIR /app

# Файлы зависимостей
COPY requirements.txt .
# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt
# Копируем исходный код
COPY . .
# Открываем порт
EXPOSE 8000
# Запуск
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]