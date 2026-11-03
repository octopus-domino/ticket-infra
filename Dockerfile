# syntax=docker/dockerfile:1

# ==========================================
# Этап 1: Сборка Frontend (React)
# ==========================================
FROM node:22-alpine AS frontend-builder
WORKDIR /app

# Установка зависит только от lock-файла, не от настроек Vite и исходников.
COPY ticket-editor/package*.json ./
RUN --mount=type=cache,id=codoc-npm,target=/root/.npm,sharing=locked \
    npm ci --prefer-offline --no-audit --no-fund

# Явно задаем переменные, чтобы Vite 100% их подхватил
ENV VITE_DRAWIO_URL="https://drawio.codoc.site/"
ENV VITE_FEATURE_DIAGRAM="true"
ENV VITE_BACKEND_URL="/"
ENV VITE_BASE_URL="/"
ENV VITE_EXPORT_API="/api/export"
ARG VITE_YANDEX_METRIKA_ID="114057241"
ENV VITE_YANDEX_METRIKA_ID=${VITE_YANDEX_METRIKA_ID}
ARG VITE_FEEDBACK_FORM_URL="https://forms.yandex.ru/u/6aea2bde49af470247e9dcf9/"
ENV VITE_FEEDBACK_FORM_URL=${VITE_FEEDBACK_FORM_URL}

# Копируем исходники без локальных node_modules (Dockerfile.dockerignore).
COPY ticket-editor/ ./
# Заменяем хардкод localhost на относительные пути для продакшена
RUN npm run check && npm test && npm run build

# ==========================================
# Этап 2: Сборка Backend (Spring Boot)
# ==========================================
FROM maven:3.9-eclipse-temurin-17 AS backend-builder
WORKDIR /app
COPY ticket-pdf/pom.xml ./
RUN --mount=type=cache,id=codoc-maven,target=/root/.m2/repository,sharing=locked \
    mvn -B -ntp dependency:go-offline
COPY ticket-pdf/src ./src
RUN --mount=type=cache,id=codoc-maven,target=/root/.m2/repository,sharing=locked \
    mvn -B -ntp clean verify

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
VOLUME ["/app/data"]

# Запускаем Supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
