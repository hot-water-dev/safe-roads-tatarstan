# Образ Node.js
FROM node:20-alpine

# Рабочая директория
WORKDIR /app

# Копируем json
COPY package*.json ./

# Устанавливаем зависимости
RUN npm ci

# Копируем исходный код
COPY . .

# Открываем порт
EXPOSE 5173

# Команда запуска (dev-сервер)
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]