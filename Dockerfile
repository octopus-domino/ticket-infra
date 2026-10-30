# ==========================================
# Этап 1: Сборка Frontend (React)
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app

# Явно задаем переменные, чтобы Vite 100% их подхватил
ENV VITE_DRAWIO_URL="https://drawio.codoc.site/"
ENV VITE_FEATURE_DIAGRAM="true"
ENV VITE_BACKEND_URL="/"
ENV VITE_BASE_URL="/"
ENV VITE_EXPORT_API="/api/export"

# Копируем локальные файлы (которые вы обновили через git pull)
COPY ticket-editor/package*.json ./
RUN npm install
COPY ticket-editor/ ./
# Заменяем хардкод localhost на относительные пути для продакшена
RUN sed -i 's|http://localhost:8080||g' src/auth/LoginPage.tsx || true
RUN npm run build

# ==========================================
# Этап 2: Сборка Backend (Spring Boot)
# ==========================================
FROM maven:3.9-eclipse-temurin-17 AS backend-builder
WORKDIR /app
COPY ticket-pdf/pom.xml ./
RUN mvn dependency:go-offline -B
COPY ticket-pdf/src ./src
RUN mvn clean package -DskipTests

# ==========================================
# Этап 3: Финальный образ (Nginx + Java)
# ==========================================
FROM eclipse-temurin:17-jre-alpine

# Устанавливаем Nginx, Supervisor (для запуска двух процессов) и curl
RUN apk add --no-cache nginx supervisor curl

# Копируем собранный JAR-файл бэкенда
COPY --from=backend-builder /app/target/*.jar /app/app.jar

# Копируем собранную статику фронтенда
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# Копируем конфиг Nginx
COPY ticket-infra/nginx.conf /etc/nginx/http.d/default.conf

# Настраиваем Supervisor
RUN mkdir -p /etc/supervisor.d && echo $'[supervisord]\n\
nodaemon=true\n\
\n\
[program:nginx]\n\
command=nginx -g "daemon off;"\n\
autostart=true\n\
autorestart=true\n\
\n\
[program:backend]\n\
command=java -jar /app/app.jar\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0' > /etc/supervisord.conf

# ВАЖНО: задаем рабочую директорию, чтобы база данных создавалась в /app/data
WORKDIR /app

# Открываем 80-й порт
EXPOSE 80

# Запускаем Supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]