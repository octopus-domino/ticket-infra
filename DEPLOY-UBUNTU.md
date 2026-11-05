# Ubuntu: CoDoc, Tesseract, 1С и клиентское API

**Для уже работающей VM с вашим `ticket-app`, bind mount `$HOME/ticket-data` и внешним Nginx используйте [DEPLOY-EXISTING-VM.md](DEPLOY-EXISTING-VM.md).** Там обновлённый `deploy.sh`, полный внешний Nginx и команды перехода. Инструкция ниже относится к отдельному сценарию полного Compose-развёртывания; не запускайте его поверх существующей установки с другим хранилищем.

Инструкция для одной Ubuntu VM, включая 2 vCPU / 4 ГБ RAM. В контейнер входят сайт, Java API, Tesseract с русским/английским языками и шрифты для PDF. Отдельные контейнеры — бесплатный Tyk Gateway и Redis. Ollama выключена. Никакие команды ниже в вашей VM автоматически не выполнялись: здесь нет её подключения, а локальный Docker daemon недоступен.

Рекомендуемый путь — Ubuntu 24.04 LTS. Команды установки Docker берутся из [официальной инструкции](https://docs.docker.com/engine/install/ubuntu/); для другой версии Ubuntu сверяйте поддерживаемые выпуски там. Существующий Docker переустанавливать не нужно. Установка пакетов и сборка требуют доступа к репозиториям; распознавание после установки выполняется локально, без внешней модели.

## 1. Установить Docker и Compose

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl openssl nginx certbot python3-certbot-nginx
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$VERSION_CODENAME" "$(dpkg --print-architecture)" | sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

Работать можно через `sudo docker`: добавление пользователя в группу Docker для этого не требуется. Проверьте свободное место под образы, npm/Maven-кэши и документы. Лимит памяти работающих сервисов — около 2,85 ГБ суммарно; это настройка, а не результат нагрузочного теста. Сборка ограничена по heap, frontend и backend собираются последовательно. На маленькой VM сборка и тесты могут занимать заметное время. Готовый образ также можно собрать на другой машине и перенести через `docker save` / `docker load`.

## 2. Перенести актуальные исходники

Рядом должны лежать три каталога, поскольку контекст сборки — их родитель:

```text
/opt/codoc/
  ticket-editor/
  ticket-pdf/
  ticket-infra/
    Dockerfile
    compose.api.yml
    tyk/
```

Из `C:\sandpr` можно создать архив без зависимостей, локальных БД и секретов:

```powershell
tar.exe --exclude="*/node_modules" --exclude="*/target" --exclude="*/.git" --exclude="*/.env*" --exclude="*/data" --exclude="*/test-results" --exclude="*/playwright-report" -czf codoc-source.tgz ticket-editor ticket-pdf ticket-infra
scp.exe codoc-source.tgz user@SERVER:/tmp/codoc-source.tgz
```

На Ubuntu:

```bash
sudo install -d -m 0750 /opt/codoc
sudo tar -xzf /tmp/codoc-source.tgz -C /opt/codoc
cd /opt/codoc/ticket-infra
```

Если используете Git, перенесите также новые файлы текущей работы: они могут ещё не находиться в коммите. `stamp-editor` и его сборка для этого развёртывания не нужны.

## 3. Создать настройки и секреты

Подставьте свои домены. Второй адрес может находиться на том же домене, например `https://docs.example.ru/client-api`.

```bash
sudo sh scripts/init-api-env.sh https://docs.example.ru https://api.example.ru/client-api
sudo docker compose --env-file .env -f compose.api.yml config --quiet
```

Скрипт создаёт `.env`, не печатает секреты и отказывается менять существующий файл. В нём независимые JWT, ключ шифрования credentials, административный ключ Tyk и пароль Redis. `APP_SECRETS_ENCRYPTION_KEY` нужно сохранять вместе с резервной копией БД. Повторная генерация этого ключа сделает сохранённые credentials источников нечитаемыми.

`CONNECTOR_ALLOWED_ORIGINS` по умолчанию пуст: приложение не сможет читать произвольные внешние базы. При настройке 1С добавьте точный origin, например `https://onec.internal:8443`. Для нескольких источников используйте запятую, без `*` и путей.

Google-вход необязателен для регистрации по почте/паролю и гостевого режима. Для реального Google OAuth задайте `GOOGLE_CLIENT_ID` и `GOOGLE_CLIENT_SECRET`; разрешённый callback — `https://docs.example.ru/login/oauth2/code/google`. Без собственных credentials кнопка Google не будет рабочим способом входа. Запуск приложения не требует получения Google discovery-документа.

## 4. Первый запуск и существующая база

**Новая пустая БД**, только первый запуск:

```bash
sudo env DB_SCHEMA_MODE=update docker compose --env-file .env -f compose.api.yml up -d --build
sudo docker compose --env-file .env -f compose.api.yml logs --tail=100 app
```

Когда приложение запустилось, верните штатный режим проверки схемы. В `.env` уже стоит `DB_SCHEMA_MODE=validate`, поэтому достаточно пересоздать приложение без одноразовой переменной:

```bash
sudo docker compose --env-file .env -f compose.api.yml up -d --force-recreate app
sudo docker compose --env-file .env -f compose.api.yml ps
```

**Существующая БД:** сначала резервная копия. Не задавайте `DB_SCHEMA_MODE=update` автоматически — запускайте обычный compose с `validate`. Additive SQL-миграции добавляют таблицы ключей, источников, версий, библиотек и профиля, затем Hibernate проверяет модель. Сохраняется volume `codoc_app-data`, Redis — `codoc_redis-data`. Если переносите старый bind mount, определите реальный путь старой БД и скопируйте его в нужный volume до запуска, не создавайте поверх неё пустую базу. В volume приложения должны оказаться `ticket-db.mv.db` и каталог `generation`.

## 5. HTTPS и reverse proxy

Контейнер приложения доступен только на `127.0.0.1:8090`, шлюз — на `127.0.0.1:8088`. Для входа с secure cookies нужен HTTPS. Создайте DNS-записи доменов на сервер и настройте системный Nginx. Пример сайта `/etc/nginx/sites-available/codoc`:

```nginx
server {
    listen 80;
    server_name docs.example.ru;
    client_max_body_size 64m;
    location /client-api/ {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_request_buffering off;
        proxy_read_timeout 180s;
    }
    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_request_buffering off;
        proxy_read_timeout 180s;
    }
}
server {
    listen 80;
    server_name api.example.ru;
    client_max_body_size 64m;
    location /client-api/ {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_request_buffering off;
        proxy_read_timeout 180s;
    }
    location / { return 404; }
}
```

Второй `server` не нужен, если API находится на домене приложения. `proxy_pass` без завершающего `/` сохраняет `/client-api/`, который Tyk затем удаляет при проксировании к Spring. Порты управления Tyk 8081 и Redis 6379 наружу не публикуются.

```bash
sudo ln -s /etc/nginx/sites-available/codoc /etc/nginx/sites-enabled/codoc
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d docs.example.ru -d api.example.ru
```

Не заменяйте существующие конфигурации других сайтов этим примером. Для внутреннего сервера без публичного DNS используйте сертификат вашей организации и доверенный CA. После настройки проверьте вход и обновление страницы по HTTPS. Нужны внешние порты 80/443 и ваш SSH; 8090, 8088, 8081 и Redis публиковать в интернет не требуется.

## 6. Проверить Tesseract и распознавание

```bash
sudo docker compose --env-file .env -f compose.api.yml exec app tesseract --version
sudo docker compose --env-file .env -f compose.api.yml exec app tesseract --list-langs
sudo docker compose --env-file .env -f compose.api.yml exec app fc-match Arial
curl --fail http://127.0.0.1:8090/api/guest/recognition/capabilities
```

В списке языков должны быть `eng` и `rus`. `capabilities` подтверждает доступность маршрута, а не качество OCR. Для приёмки откройте библиотеку → создание по изображению, загрузите чистый PNG/JPEG с русским текстом и таблицей, распознайте и сравните с оригиналом. Проверьте правку текста, редактирование таблицы и PDF. Одновременно выполняется одно OCR-задание; `OMP_THREAD_LIMIT=1`. Фотография с перспективой, смазанный текст или печать на фоне не гарантируют точного распознавания.

Tesseract не требует платной лицензии, API-ключа облачной модели, GPU или Ollama. На вашей VM основной режим — `ocr`. Для vision-модели нужна отдельная более мощная машина в частной сети; настройки и оценка памяти описаны в HTML v6.1. Образ содержит только нужные языки OCR; набор шрифтов для PDF — отдельный пакет.

## 7. Выпустить и проверить клиентский API-ключ

1. Зарегистрировать владельца по HTTPS.
2. Открыть «Клиентское API», задать понятное название и права. Для OCR/генерации нужны `generate`, для чтения каталогов — `read`, для изменения схем/моделей/шаблонов — `data:write`.
3. Скопировать ключ сразу; в списке он целиком больше не показывается.
4. Проверить запрос с внешней машины, затем отзыв и повторный отказ.

```bash
read -r -s -p 'API key: ' CODOC_API_KEY
printf '\n'
curl --fail-with-body -H "X-API-Key: $CODOC_API_KEY" https://api.example.ru/client-api/templates
unset CODOC_API_KEY
```

Без ключа Tyk должен отказать. Если выпуск ключа возвращает ошибку шлюза, проверьте `logs gateway redis` и одинаковый `TYK_ADMIN_SECRET` в compose, не печатайте его в общие логи. Квоты и административные маршруты описаны в [API-GATEWAY.md](API-GATEWAY.md). Открытие оплачиваемого Tyk Dashboard не требуется: управление клиентскими ключами реализовано в CoDoc.

## 8. Подключить 1С

Два независимых направления:

- **1С вызывает CoDoc:** перенести функции из [examples/one-c-generation.bsl](examples/one-c-generation.bsl) в подходящий общий модуль вашей конфигурации/расширения. `СформироватьДокументCoDoc` создаёт PDF, `РаспознатьФотоCoDoc` возвращает JSON-черновик OCR без сохранения шаблона. Адрес API и ключ передаются параметрами; ключ хранится в защищённых настройках 1С. Это исходный BSL-модуль для встраивания, а не собранное `.cfe` или `.epf`. Прогон на вашей версии платформы обязателен.
- **CoDoc читает 1С:** опубликовать OData или HTTP JSON в вашей базе, выдать отдельному пользователю только нужные права, разрешить origin в `.env` и пересоздать `app`. В разделе «Источники данных» добавить подключение, загрузить preview, выбрать схему, сопоставить поля и стабильный `Ref_Key`, проверить строки и импортировать. Повторный импорт обновляет записи. Описания всех конфигураций 1С не зашиты в код: имена коллекций и полей выбираются для вашей базы.

Если 1С находится внутри сети, её адрес должен быть доступен **из контейнера** приложения. `127.0.0.1` внутри контейнера — сам контейнер, не сервер 1С. Для многостраничных ответов настройте полный фильтрованный экспорт: автоматический обход всех страниц не реализован, а автообновление неполного набора блокируется.

## 9. Резервирование и обновление

Сохранять нужно `.env`, volume приложения с БД/выпусками и Redis volume. Копировать работающий файл H2 обычным `cp` нельзя: для простой согласованной копии остановите сервисы на короткое время.

```bash
cd /opt/codoc/ticket-infra
backup_dir="/var/backups/codoc/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 0700 "$backup_dir"
image_id=$(sudo docker compose --env-file .env -f compose.api.yml images -q app)
sudo docker compose --env-file .env -f compose.api.yml stop app gateway redis
sudo docker run --rm --network none --entrypoint tar -v codoc_app-data:/data:ro -v "$backup_dir":/backup "$image_id" -czf /backup/app-data.tgz -C /data .
sudo docker run --rm --network none --entrypoint tar -v codoc_redis-data:/data:ro -v "$backup_dir":/backup "$image_id" -czf /backup/redis-data.tgz -C /data .
sudo install -m 0600 .env "$backup_dir/.env"
sudo docker compose --env-file .env -f compose.api.yml up -d
```

Перед восстановлением остановите сервисы, сохраните текущие volumes отдельно и распаковывайте резервную копию только в явно выбранные целевые volumes. Секреты должны соответствовать сохранённой БД/Redis. `docker compose down -v` удаляет данные и не является обычным шагом обновления.

Обновление после резервной копии и переноса новых исходников:

```bash
sudo docker compose --env-file .env -f compose.api.yml build app
sudo docker compose --env-file .env -f compose.api.yml up -d
sudo docker compose --env-file .env -f compose.api.yml logs --tail=100 app gateway
```

## Что считается завершённой приёмкой

Сервисы стартуют; OCR распознаёт ваш тестовый русский документ; PDF показывает изображения и подписи draw.io; реальный сертификат подписывает полученные байты; клиентский ключ проходит через Tyk и перестаёт работать после отзыва; 1С выполняет повторный импорт без дублей; после перезапуска сохраняются аккаунт, профиль и документы. На текущей машине разработки проверены код и автоматические сценарии, но не запуск этого набора на Ubuntu, реальная база 1С и реальный сертификат.
