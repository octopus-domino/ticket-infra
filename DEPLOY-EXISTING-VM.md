# Обновление существующей VM: deploy.sh + внешний Nginx

Эта инструкция соответствует вашей установке: три Git-репозитория рядом, `.env` в их общей папке, контейнер `ticket-app`, данные в `$HOME/ticket-data`, внешний Nginx с действующим сертификатом `codoc.site`. Приложение остаётся одним контейнером (внутренний Nginx + Java + Tesseract). Для выдачи клиентских API-ключей скрипт дополнительно запускает Tyk и Redis. Их настройка не переносит базу приложения в новый Docker volume.

Файлы:

- `ticket-infra/deploy.sh` — обновление и запуск вместо старого скрипта.
- `ticket-infra/nginx.external.conf` — полный конфиг **внешнего** Nginx.
- `ticket-infra/deploy.env.example` — новые переменные; объединить с существующим `.env`.
- `ticket-infra/compose.gateway.yml` — только Tyk и Redis. `compose.api.yml` в этом сценарии **не запускать**: он создаёт отдельное приложение с другим хранилищем.

Ниже `/opt/codoc` — пример. Замените его на папку, где у вас уже лежат три репозитория и старый скрипт. Команды выполняются от того же пользователя, который раньше запускал развёртывание. Не запускайте новый скрипт через `sudo`, если это изменит `$HOME` и путь к данным. Если раньше всё запускалось от root, продолжайте от root с прежним `DATA_DIR`.

## 1. Проверить текущую установку — вне скрипта

```bash
cd /opt/codoc
pwd
ls -d ticket-editor ticket-pdf ticket-infra
docker version
docker compose version
docker inspect --format '{{range .Mounts}}{{println .Type .Source "->" .Destination}}{{end}}' ticket-app
docker ps --format 'table {{.Names}}\t{{.Ports}}'
free -h
swapon --show
df -h . "$HOME"
```

В `docker inspect` должно быть прежнее хранилище, например `/home/ubuntu/ticket-data -> /app/data`. Запишите этот путь. Скрипт сверяет его перед остановкой и отказывается запускаться с другой папкой. Внешний Nginx и сертификаты повторно устанавливать не нужно. Docker Compose нужен только для Tyk/Redis. Если команды `docker compose` нет, установите плагин из того же официального Docker-репозитория, который используется на сервере:

```bash
sudo apt-get update
sudo apt-get install -y docker-compose-plugin
docker compose version
```

Если `apt` не находит пакет, используйте [инструкцию Docker для Ubuntu](https://docs.docker.com/engine/install/ubuntu/); не удаляйте рабочий Docker ради этого шага. Для самого скрипта нужны `git`, `curl`, `tar`, `realpath`, `flock`:

```bash
sudo apt-get install -y git curl tar coreutils util-linux openssl
```

### Если на 4 ГБ RAM совсем нет swap

Сборка выполняет тесты, пока работает предыдущий контейнер. Дополнительные 4 ГБ swap уменьшают риск нехватки памяти при сборке, но не ускоряют её. Выполнить один раз **только если `swapon --show` пуст**, есть свободное место и `/swapfile` ещё не существует:

```bash
test ! -e /swapfile
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
printf '/swapfile none swap sw 0 0\n' | sudo tee -a /etc/fstab
swapon --show
```

Останавливайтесь при любой ошибке; не переформатируйте уже существующий swap. Лимиты скрипта: приложению 2304 МиБ RAM, Java heap до 1536 МиБ, Tyk 384 МиБ, Redis 160 МиБ; итог зависит от документов и нагрузки. CPU приложения ограничен двумя ядрами. [Семантика лимитов Docker](https://docs.docker.com/engine/containers/resource_constraints/).

## 2. Доставить актуальный код — вне скрипта при первом переходе

Изменения, подготовленные в локальной рабочей папке, сами по себе не попадут в `git pull`: сначала они должны быть закоммичены и отправлены в ваши удалённые репозитории либо перенесены на VM. В этой сессии push не выполнялся.

Если изменения уже находятся в удалённых репозиториях:

```bash
cd /opt/codoc
git -C ticket-editor status --short
git -C ticket-pdf status --short
git -C ticket-infra status --short
git -C ticket-editor pull --ff-only
git -C ticket-pdf pull --ff-only
git -C ticket-infra pull --ff-only
```

Если `status` показывает локальные изменения, сначала сохраните их осознанно; скрипт не делает `reset`, `clean` или принудительный checkout. Для файлов, доставленных без Git-коммита, предусмотрен `SKIP_GIT_PULL=true` при запуске. Это собирает именно доставленные исходники.

Проверить новый файл:

```bash
cd /opt/codoc
chmod +x ticket-infra/deploy.sh
bash -n ticket-infra/deploy.sh
```

Если файл переносился через Windows и содержит CRLF:

```bash
sed -i 's/\r$//' ticket-infra/deploy.sh
bash -n ticket-infra/deploy.sh
```

При желании сохранить привычный старый путь скрипта, замените **его содержимое** небольшой обёрткой. Например для старого `/opt/codoc/deploy.sh`:

```bash
cp -p deploy.sh "deploy.sh.before-$(date -u +%Y%m%dT%H%M%SZ)"
cat > deploy.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec bash ticket-infra/deploy.sh "$@"
EOF
chmod +x deploy.sh
```

Этот блок выполнять, только если старый файл действительно называется `deploy.sh`. Обёртка не обязательна: можно запускать `bash ticket-infra/deploy.sh` напрямую.

## 3. Дополнить существующий .env — вне скрипта, один раз

**Не копируйте пример поверх рабочего `.env`.** Сохраните имеющиеся Google OAuth и JWT-секреты. Сделайте закрытую резервную копию и откройте файл:

```bash
cd /opt/codoc
cp -p .env ".env.before-$(date -u +%Y%m%dT%H%M%SZ)"
chmod 600 .env .env.before-*
openssl rand -hex 32
openssl rand -hex 32
nano .env
```

Два разных результата `openssl` вписать как `TYK_ADMIN_SECRET` и `REDIS_PASSWORD`. Пример добавляемых строк:

```bash
APP_FRONTEND_URL=https://www.codoc.site
DEPLOY_CLIENT_API=true
TYK_ADMIN_SECRET='ПЕРВЫЙ_СЛУЧАЙНЫЙ_СЕКРЕТ_64_HEX'
REDIS_PASSWORD='ВТОРОЙ_СЛУЧАЙНЫЙ_СЕКРЕТ_64_HEX'
APP_CLIENT_API_PUBLIC_URL=https://www.codoc.site/client-api
APP_CONNECTORS_ALLOWED_ORIGINS=''
# Укажите абсолютный путь из docker inspect, если он отличается от $HOME/ticket-data:
# DATA_DIR=/home/ubuntu/ticket-data
# BACKUP_DIR=/home/ubuntu/ticket-backups
```

`JWT_SECRET` менять не надо. Если раньше `APP_SECRETS_ENCRYPTION_KEY` не задавался, скрипт продолжит использовать существующий `JWT_SECRET`: иначе сохранённые секреты интеграций и ключи нельзя будет расшифровать. Если отдельный ключ шифрования уже задан — сохраните именно его. Секреты Tyk/Redis после первого запуска тоже не меняйте произвольно.

`.env` остаётся shell-файлом, как в вашем старом скрипте. Значения с пробелами, `$`, `#`, `!` заключайте в одинарные кавычки. Пароли не передаются аргументами `docker run` открытым текстом: используются имена экспортированных переменных.

Для внешних источников 1С/Bitrix24/amoCRM укажите **точные доверенные HTTPS origins**, без пути, например:

```bash
APP_CONNECTORS_ALLOWED_ORIGINS='https://1c.example.ru,https://company.bitrix24.ru'
```

Для исходящих писем добавьте ваши реальные `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_SSL`, `SMTP_TLS`, `EMAIL_FROM`. Порт 465 обычно используется с `SMTP_SSL=true`, `SMTP_TLS=false`; для вашего SMTP сверяйтесь с его настройками. Без действительных SMTP-реквизитов отправка писем не считается настроенной.

Ollama скрипт выключает: на 2 CPU / 4 ГБ используется локальный Tesseract с `rus` и `eng`, уже включённый в Dockerfile. Устанавливать Tesseract в Ubuntu отдельно не нужно.

Если клиентский API пока не нужен, задайте `DEPLOY_CLIENT_API=false`. Тогда Tyk/Redis не запускаются, секреты для них не обязательны. Уже запущенные сервисы скрипт при этом автоматически не удаляет и не останавливает.

## 4. Обновить внешний Nginx — вне скрипта, один раз

Найдите текущий файл именно для `codoc.site`, не трогая отдельный сайт `drawio.codoc.site`:

```bash
sudo nginx -T 2>&1 | less
ls -l /etc/nginx/sites-enabled/
sudo openssl x509 -in /etc/letsencrypt/live/codoc.site/fullchain.pem -noout -ext subjectAltName
```

Сертификат должен покрывать `codoc.site` и `www.codoc.site`, как в вашей действующей конфигурации. Ниже предполагается, что текущая ссылка `sites-enabled/codoc` указывает на `sites-available/codoc`. Если у вас другое имя, замените его во всех командах:

```bash
cd /opt/codoc
sudo cp -p /etc/nginx/sites-available/codoc "/etc/nginx/sites-available/codoc.before-$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -m 644 ticket-infra/nginx.external.conf /etc/nginx/sites-available/codoc
sudo nginx -t
sudo systemctl reload nginx
```

`reload` выполнять **только если `nginx -t` успешен**. Не создавайте второй `server_name` для тех же доменов в другом включённом файле. Если проверка не прошла, верните сохранённый файл и повторите `nginx -t`.

Что изменено:

- Внешний Nginx продолжает направлять сайт на `127.0.0.1:8080`.
- `/client-api/` направляется на Tyk, `127.0.0.1:8088`, с сохранением префикса пути.
- Управляющий порт Tyk 8081 и Redis не публикуются на хосте.
- Сохраняются `Cache-Control` приложения; прежний `proxy_hide_header Cache-Control` удалён.
- Полная CSP разрешает draw.io, встроенные PDF, формы обратной связи и используемые адреса Метрики. В присланном сообщении строка CSP обрезана — её нельзя копировать как готовую строку конфигурации.
- Заголовки безопасности задаются внешним Nginx один раз, без второй CSP из контейнера.
- `codoc.site` перенаправляется на `www.codoc.site`, чтобы OAuth и cookies использовали один адрес. Google redirect URI должен остаться `https://www.codoc.site/login/oauth2/code/google`.
- Origin для preflight — `https://www.codoc.site` **без завершающего `/`**.

Устанавливать или менять конфигурацию `drawio.codoc.site` этим файлом не нужно. Во время первого перехода до старта Tyk путь `/client-api/` временно отдаёт 502; сайт продолжает работать.

## 5. Развернуть — один запуск скрипта

Обычное обновление из Git:

```bash
cd /opt/codoc
bash ticket-infra/deploy.sh
```

Если актуальные исходники перенесены вручную и ещё не закоммичены:

```bash
cd /opt/codoc
SKIP_GIT_PULL=true bash ticket-infra/deploy.sh
```

Для принудительной пересборки без layer cache, если действительно потребуется:

```bash
NO_CACHE=true bash ticket-infra/deploy.sh
```

Не ставьте эти флаги в `.env`, если хотите менять их перед отдельным запуском. По умолчанию BuildKit использует кэш; тесты новых исходников выполняются при пересборке изменившихся слоёв. Зависимости npm/Maven кешируются. На этой VM сборка может идти заметно дольше, чем локально.

Скрипт сам:

1. Исключает параллельное развёртывание, проверяет переменные, доступ к Docker и путь существующей БД.
2. Выполняет `git pull --ff-only` в трёх репозиториях, если не передан `SKIP_GIT_PULL=true`.
3. Собирает новый образ с отдельным тегом, сохраняя работающий старый контейнер на время сборки.
4. Поднимает Tyk/Redis и общую сеть при `DEPLOY_CLIENT_API=true`.
5. Останавливает приложение, создаёт согласованный архив **всего** `/app/data`, копию `.env`, записывает Git revision и id старого образа в `$HOME/ticket-backups/<метка>/`.
6. Сохраняет остановленный старый контейнер как `ticket-app-previous-<метка>`.
7. Запускает новый `ticket-app` с прежними данными, `prod`, SQL-миграциями и Hibernate `validate`, SMTP и настройками API. Порт 8080 доступен только с локальной машины.
8. Ждёт готовности Spring и сайта по HTTP, проверяет языки Tesseract, HTTPS, preflight и отказ клиентского API без ключа.

Файл `ticket-db.lock.db` скрипт **не удаляет**. Резервная копия создаётся после остановки Java, а не во время записи H2. Предыдущий контейнер и данные не удаляются автоматически.

Для вашей существующей установки `FIRST_INSTALL=true` не нужен. Он предназначен только для новой пустой папки без `ticket-db.mv.db`: первичный запуск создаёт схему с `update`, затем приложение пересоздаётся с `validate`. Скрипт запрещает этот режим поверх существующей БД.

Если построение образа упало, старый сайт остаётся работать. Если ошибка произошла при архивировании до замены, скрипт пытается вернуть старый контейнер. Если не поднялось новое приложение после миграций, оно останавливается; автоматического отката БД нет. Ошибка только внешней HTTPS-проверки оставляет исправное локальное приложение работать и возвращает ненулевой код.

## 6. Приёмка после запуска — вне скрипта

```bash
cd /opt/codoc
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker logs --tail 100 ticket-app
docker stats --no-stream
curl -fsS https://www.codoc.site/api/guest/recognition/capabilities
docker exec ticket-app tesseract --version
docker exec ticket-app tesseract --list-langs
docker exec ticket-app fc-match Arial
curl -sSI https://codoc.site/
curl -sSI https://www.codoc.site/
curl -sS -o /dev/null -w '%{http_code}\n' https://www.codoc.site/client-api/recognition/capabilities
```

Ожидания: сайт доступен по HTTPS, `capabilities` показывает `ocr:true`, `ollama:false`, в языках есть `rus` и `eng`. Клиентский API без ключа возвращает 401/403, а не 200/502. Публикуются только `127.0.0.1:8080` и `127.0.0.1:8088`; наличие 8081 или 6379 в колонке без host mapping ещё не означает публикации на хосте.

Проверка реального OCR без регистрации на чёткой картинке:

```bash
umask 077
export CODOC_TEST_IMAGE="$HOME/test-document.png"
python3 - <<'PY' > /tmp/codoc-ocr-request.json
import base64, json, os
with open(os.environ['CODOC_TEST_IMAGE'], 'rb') as image:
    encoded = base64.b64encode(image.read()).decode('ascii')
print(json.dumps({'image': 'data:image/png;base64,' + encoded, 'language': 'rus+eng', 'engine': 'ocr'}))
PY
curl -fS --max-time 180 https://www.codoc.site/api/guest/recognition \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/codoc-ocr-request.json \
  -o /tmp/codoc-ocr-result.json
python3 -m json.tool /tmp/codoc-ocr-result.json | less
rm -f /tmp/codoc-ocr-request.json /tmp/codoc-ocr-result.json
```

Для JPEG замените MIME на `image/jpeg`; пример с PNG не конвертирует файл. Временные JSON содержат изображение/распознанные данные, поэтому перед примером можно выполнить `umask 077`. В браузере дополнительно проверить: вход Google, профиль, гостевой документ, импорт фотографии, сохранение шаблона, генерацию своего проблемного draw.io в PDF/PDF-A и подписание с вашим настоящим сертификатом.

### Клиентский API и 1С

Войти в CoDoc → раздел выдачи API-ключей → создать ключ с необходимыми правами → один раз сохранить выданный секрет. Не использовать `TYK_ADMIN_SECRET` как клиентский ключ. Для ручной проверки:

```bash
read -rsp 'Client API key: ' CODOC_CLIENT_KEY; printf '\n'
curl -fS https://www.codoc.site/client-api/recognition/capabilities \
  -H "X-API-Key: $CODOC_CLIENT_KEY"
unset CODOC_CLIENT_KEY
```

В 1С взять `ticket-infra/examples/one-c-generation.bsl`, указать адрес `www.codoc.site` и выданный **клиентский** ключ. Есть примеры генерации PDF и распознавания фотографии. Это BSL-код для встраивания разработчиком 1С, не готовый устанавливаемый `.cfe/.epf`. Настройки прав и endpoint описаны в [API-GATEWAY.md](API-GATEWAY.md). Сам скрипт не знает паролей вашей 1С и не устанавливает код внутрь её конфигурации.

## 7. Последующие обновления

После настройки `.env` и внешнего Nginx достаточно:

```bash
cd /opt/codoc
bash ticket-infra/deploy.sh
```

При этом каждый запуск создаёт новую резервную копию и сохраняет предыдущий контейнер. Контролируйте свободный диск; старые копии/образы удалять только после приёмки нужного выпуска. Скрипт не выполняет `docker system prune`, не удаляет volumes и не чистит резервные копии.

## 8. Откат при неуспешном запуске

После миграции старый образ нельзя без проверки запускать на изменённой базе. Укажите **конкретные** метку резервной копии и имя предыдущего контейнера из вывода скрипта. Следующий способ сохраняет изменённую папку отдельно и восстанавливает архив в исходный путь; существующие данные не удаляются.

```bash
cd /opt/codoc
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
ls -lt "$HOME/ticket-backups"

# Заменить значения реальными, не вводить буквально METKA:
BACKUP="$HOME/ticket-backups/METKA"
PREVIOUS='ticket-app-previous-METKA'
DATA_DIR='/home/ubuntu/ticket-data'

test -f "$BACKUP/data.tgz"
docker inspect "$PREVIOUS" >/dev/null
docker stop --time 60 ticket-app
docker rename ticket-app "ticket-app-failed-$(date -u +%Y%m%dT%H%M%SZ)"
sudo mv -- "$DATA_DIR" "$DATA_DIR.failed-$(date -u +%Y%m%dT%H%M%SZ)"
sudo mkdir -p -- "$DATA_DIR"
sudo tar -xzf "$BACKUP/data.tgz" -C "$DATA_DIR"
docker rename "$PREVIOUS" ticket-app
docker start ticket-app
docker logs --tail 100 ticket-app
curl -fsS https://www.codoc.site/api/guest/recognition/capabilities
```

Команды выполнять по одной и останавливать последовательность при ошибке. До перемещения папки убедитесь, что приложение остановлено и `DATA_DIR` точно совпадает с его bind mount. Восстановление возвращает состояние на момент копии; изменения после неё остаются в `.failed-*`, но не входят в восстановленную БД. Настройки старого контейнера сохранены в самом контейнере; закрытая копия `.env` лежит в каталоге резервной копии. Tyk/Redis и внешний Nginx этим откатом не меняются. Старый контейнер из вашего прежнего скрипта может снова публиковать `0.0.0.0:8080`: проверьте порты и сетевой экран.

## 9. Если что-то не работает

```bash
docker logs --tail 150 ticket-app
docker inspect --format 'OOM={{.State.OOMKilled}} exit={{.State.ExitCode}}' ticket-app
sudo nginx -t
sudo tail -n 100 /var/log/nginx/error.log
curl -v http://127.0.0.1:8080/api/guest/recognition/capabilities
```

Для логов шлюза загрузить те же переменные из доверенного `.env`, не печатая их:

```bash
cd /opt/codoc
set -a
source .env
set +a
docker compose --project-name codoc-gateway --env-file /dev/null -f ticket-infra/compose.gateway.yml logs --tail 100 gateway redis
```

- **502 только у `/client-api/`**: проверить Tyk/Redis, путь в Nginx, сеть `codoc-client-api` и alias `app` контейнера `ticket-app`.
- **Schema-validation**: не переключать рабочую БД на `update` вслепую. Сохранить сообщение и копию; проверить, что используется актуальный backend и правильная прежняя папка данных.
- **Ошибка входа Google**: проверить `APP_FRONTEND_URL` и разрешённый redirect URI в Google Console; `X-Forwarded-Proto` должен доходить как `https`.
- **Письма не уходят**: SMTP-реквизиты и доступность порта провайдера; публичный домен сайта не является SMTP-сервером.
- **Tesseract доступен, но результат плохой**: пробовать прямой, резкий снимок без перспективы и теней. Автоматическое восстановление сложной схемы/таблицы не гарантирует точную копию исходного дизайна.

Локально проверяются синтаксис Bash, сценарии скрипта с подменённым Docker и согласованность конфигураций. Настоящий запуск Docker, Nginx и сертификатов необходимо выполнить на VM; доступа к ней в этой сессии нет.
