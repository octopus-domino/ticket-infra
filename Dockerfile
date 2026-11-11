# syntax=docker/dockerfile:1

# ==========================================
# Этап 1: Сборка Frontend (React)
# ==========================================
FROM node:22-alpine AS frontend-builder
WORKDIR /app
ENV NODE_OPTIONS="--max-old-space-size=768" UV_THREADPOOL_SIZE=2 GOMAXPROCS=2
ENV VITE_BUILD_SOURCEMAP=false

# Установка зависит только от lock-файла, не от настроек Vite и исходников.
COPY ticket-editor/package*.json ./
RUN --mount=type=cache,id=codoc-npm,target=/root/.npm,sharing=locked \
    npm ci --prefer-offline --no-audit --no-fund

# Явно задаем переменные, чтобы Vite 100% их подхватил
ENV VITE_DRAWIO_URL="https://drawio.codoc.site/"
ENV VITE_FEATURE_DIAGRAM="true"
ARG VITE_FEATURE_EMAIL="true"
ENV VITE_FEATURE_EMAIL=${VITE_FEATURE_EMAIL}
ENV VITE_BACKEND_URL="/"
ENV VITE_BASE_URL="/"
ENV VITE_EXPORT_API="/api/export"
ARG VITE_YANDEX_METRIKA_ID="114057241"
ENV VITE_YANDEX_METRIKA_ID=${VITE_YANDEX_METRIKA_ID}
ARG VITE_FEEDBACK_FORM_URL="https://forms.yandex.ru/u/6aea2bde49af470247e9dcf9/"
ENV VITE_FEEDBACK_FORM_URL=${VITE_FEEDBACK_FORM_URL}
ARG VITE_YANDEX_VERIFICATION=""
ENV VITE_YANDEX_VERIFICATION=${VITE_YANDEX_VERIFICATION}
ARG VITE_GOOGLE_SITE_VERIFICATION=""
ENV VITE_GOOGLE_SITE_VERIFICATION=${VITE_GOOGLE_SITE_VERIFICATION}

# Копируем исходники без локальных node_modules (Dockerfile.dockerignore).
COPY ticket-editor/ ./
# Заменяем хардкод localhost на относительные пути для продакшена
RUN npm run check && npm test -- --maxWorkers=1 --minWorkers=1 && npm run build

# ==========================================
# Этап 2: Сборка Backend (Spring Boot)
# ==========================================
FROM maven:3.9-eclipse-temurin-17 AS backend-builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ENV MAVEN_OPTS="-Xms64m -Xmx384m -XX:MaxMetaspaceSize=192m -XX:ActiveProcessorCount=2"
# Serialize build stages on the small target VM instead of running Node and Maven together.
COPY --from=frontend-builder /app/dist /tmp/frontend-dist
COPY ticket-pdf/pom.xml ./
RUN --mount=type=cache,id=codoc-maven,target=/root/.m2/repository,sharing=locked \
    mvn -B -ntp dependency:go-offline
COPY ticket-pdf/src ./src
RUN --mount=type=cache,id=codoc-maven,target=/root/.m2/repository,sharing=locked \
    mvn -B -ntp -T1 -DforkCount=1 -DreuseForks=true \
      '-DargLine=-Xmx768m -XX:MaxDirectMemorySize=128m -XX:ActiveProcessorCount=2' clean verify

# ==========================================
# Этап 3: Финальный образ (Nginx + Java)
# ==========================================
FROM eclipse-temurin:17-jdk-alpine AS migration
WORKDIR /migration
COPY --from=backend-builder /app/target/*.jar /migration/app.jar
RUN jar xf app.jar BOOT-INF/lib && rm app.jar
COPY ticket-pdf/tools/H2ToPostgres.java /migration/H2ToPostgres.java
ENTRYPOINT ["java", "-Xmx512m", "-cp", "/migration/BOOT-INF/lib/*", "/migration/H2ToPostgres.java"]

FROM eclipse-temurin:17-jre-alpine AS runtime

# Устанавливаем Nginx, Supervisor (для запуска двух процессов) и curl
RUN apk add --no-cache nginx supervisor curl fontconfig font-dejavu font-liberation font-noto-cjk tesseract-ocr tesseract-ocr-data-eng tesseract-ocr-data-rus

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
