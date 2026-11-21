# Раздельная публикация и проверки

Скрипты используют установленный OpenSSH (`ssh`, `scp`), Python 3.10+ локально и Python 3.10+ на сервере. Для сборки нужны зависимости соответствующего проекта; для Android — JDK и Android SDK. Браузерные проверки используют Playwright из `private_jorney/node_modules`.

Адрес сервера задаётся `--target`, адрес сайта — `--base-url`. SSH берёт ключ из вашего агента или пользовательского SSH config; при необходимости передайте `--identity <путь-к-внешнему-ключу>`. Скрипты не читают содержимое ключей и не копируют их на сервер. Пароли, токены, cookies, ключи API, исходные документы и личные каталоги в этот набор не включены.

Примеры ниже запускаются из `ticket-infra` в PowerShell. Замените SSH alias `codoc-ssh` и адрес `https://example.org` своими значениями.

## Только фронт

```powershell
./scripts/build-runtime-web.ps1 -ProjectRoot ../private_jorney -Component private-journey -OutputDirectory ../.cache/private-web
python scripts/runtime_publish.py --target codoc-ssh web --component private-journey --dist ../.cache/private-web

./scripts/build-runtime-web.ps1 -ProjectRoot ../ticket-editor -Component editor -OutputDirectory ../.cache/editor-web
python scripts/runtime_publish.py --target codoc-ssh web --component editor --dist ../.cache/editor-web
```

Прогулки публикуются в `/usr/share/nginx/html/private-journey/`, редактор — в `/usr/share/nginx/html/`. Сначала доставляются ресурсы, `index.html` — последним. Старые ресурсы с хешами сохраняются для уже открытых вкладок. Java не перезапускается. Полная сборка редактора включает его штатные проверки и подготовку страниц.

## Только изменённые классы бэка

Сначала выполните Maven-проверки и компиляцию в `ticket-pdf` с целевой Java 17. Публикуются только явно указанные префиксы классов, включая вложенные классы. Например, исправление поиска области:

```powershell
python scripts/runtime_publish.py --target codoc-ssh backend --classes ../ticket-pdf/target/classes `
  --class-prefix ru/ticket/journey/PlaceRecommendationsController `
  --class-prefix ru/ticket/journey/OsmPlaceService `
  --class-prefix ru/ticket/journey/infrastructure/poi/WalkAreaSearchService `
  --class-prefix ru/ticket/journey/application/map/AreaSearchCoordinator `
  --class-prefix ru/ticket/journey/infrastructure/poi/AreaResultCache
```

Для распознавания вместо этих префиксов можно указать `--class-prefix ru/ticket/recognition/`. Изменения зависимостей, конфигурационных ресурсов, миграций или пакетов Java требуют штатной полной сборки. Пример поиска области применим после установки образа с новой структурой пакетов.

JAR проверяется как ZIP с сохранением метаданных вложенных библиотек Spring Boot. Перед заменой сохраняется Docker-образ с тегом `before-runtime-*`. Перезапускается только Java-процесс `/app/app.jar` под существующим Supervisor. Статика и Nginx остаются на месте.

Готовность определяется HTTP 200 от публичного `/api/journeys/routes/places/themes`. Защищённый `/actuator/health` не используется. При неудачном запуске восстанавливаются предыдущие JAR и тег образа, затем повторно проверяется готовность. При нехватке места скрипт прекращает работу до перезапуска: требуется 512 MiB для бэка, 128 MiB для фронта. Общий `docker compose down`, изменение или перезагрузка внешнего Nginx не выполняются.

Параметр `--container` позволяет выбрать существующий контейнер вместо `codoc-app-1`. Автоматическое сохранение обновления поддерживает образ `codoc-app` / `codoc-app:latest`. Исходники коммитятся и отправляются в Git отдельно; публикация доставляет проверенные артефакты, без `git pull` и пересборки остальных сервисов.

## Проверки сайта и логи

```powershell
python scripts/check_runtime_api.py --base-url https://example.org
python scripts/check_runtime_api.py --base-url https://example.org --area
python scripts/check_runtime_api.py --base-url https://example.org --radius-growth --trip
python scripts/runtime_logs.py --target codoc-ssh --minutes 30 --tail 500
node scripts/check_runtime_browser.mjs --frontend-root ../private_jorney --base-url https://example.org --map
node scripts/check_runtime_browser.mjs --frontend-root ../private_jorney --base-url https://example.org --handoff
```

API-проверка строит короткий пеший маршрут по тестовым координатам Петербурга. `--area` добавляет три одинаковых одновременных поиска, затем расширение радиуса и изменение категорий. `--radius-growth` проверяет увеличение радиуса, признак полноты покрытия, повтор и прогретый ответ. `--trip` проверяет статусы поставщиков и доступ к приватной поездке. Браузерный `--handoff` проверяет передачу маршрута из Journey в выбранный день. Для установленного Edge передайте `--channel msedge`. Координаты можно заменить параметрами `--longitude` и `--latitude`. Проверки не создают учётные записи или сохранённые документы на сервере. Браузерная проверка карты создаёт синтетическую запись только во временном профиле браузера и проверяет кеш тайлов при заблокированной сети.

Логи ограничены по времени и количеству строк; строки с полями авторизации, cookies, паролями и ключами пропускаются. Полученные логи и снимки экрана также могут содержать пользовательские данные — храните их вне Git.

## APK

```powershell
./scripts/build-private-apk.ps1 -ProjectRoot ../private_jorney -ApiBase https://example.org `
  -JavaHome 'D:/tools/jdk-21' -AndroidHome 'D:/tools/android-sdk' -OutputFile ../.cache/private-walks.apk
```

Выполняются тесты фронта, сборка, Capacitor sync, Android unit-тесты и `assembleDebug`. Версия берётся из `android/app/build.gradle`, автоматически не меняется. Итоговый APK подписан штатным debug-ключом локального Android-окружения; ключи подписи в репозиторий не добавляются. Изменённые переменные окружения восстанавливаются после выполнения.

## Серверный Tesseract и API распознавания

```powershell
python scripts/check_server_tesseract.py --target codoc-ssh --image ../.cache/sample.png --output-dir ../.cache/ocr-check --psm 3 11
python scripts/check_recognition_api.py --base-url https://example.org --file ../.cache/sample.pdf --page 1 --output ../.cache/recognition-result.json
```

Первый скрипт запускает установленный в контейнере Tesseract с `rus+eng`, OEM 1 и одним вычислительным потоком. Временные изображения на сервере удаляются в `finally`, TSV остаются только в указанной локальной папке. Для PDF подготовьте изображение нужной страницы либо используйте вторую команду. API-проверка принимает также изображение и сохраняет результат распознавания только в явно указанном месте. Используйте свои тестовые файлы; документы и результаты могут содержать личные данные.

## Временные каталоги и тесты скриптов

```powershell
python scripts/cleanup_runtime_releases.py --target codoc-ssh --older-hours 24
python scripts/cleanup_runtime_releases.py --target codoc-ssh --older-hours 24 --execute
python scripts/runtime_disk.py --target codoc-ssh
python scripts/runtime_disk.py --target codoc-ssh --prune-build-cache --reserve-mib 512
python -m unittest discover -s scripts/tests -p test_runtime_publish.py
```

Очистка по умолчанию показывает кандидатов. Удаляются только старые каталоги `/tmp/codoc-runtime-release-*` с собственным маркером, без перехода по симлинкам. Данные приложения, Docker volumes и образы эта команда не удаляет. Одновременную публикацию нескольких компонентов не запускайте: образ приложения общий.

`runtime_disk.py` показывает свободное место и расход Docker. С явным `--prune-build-cache` удаляет только неиспользуемый кеш сборки, сохраняя указанный резерв. Последующие сборки могут занять больше времени; контейнеры, образы, volumes и пользовательские документы не удаляются.

## Ostrovok catalog adapter

On the server, update the existing ticket-infra Git checkout with a fast-forward pull and run
`bash scripts/publish-ostrovok-runtime.sh`. It validates the committed adapter source, updates and
restarts only the existing Ostrovok MCP container, checks health and rolls back the file on failure.
The image tag used by Compose is persisted after the health check.

## Docker cleanup after deployment

After a successful health check, full deployments, PostgreSQL migration,
frontend and backend runtime publishing, and Ostrovok runtime publishing run
`scripts/lib/post-deploy-docker-cleanup.sh` on the deployment host. It removes
unused cache from the default Docker builder and dangling images. It keeps
tagged rollback images, stopped containers, volumes, and backups. The separate
resource-limited Buildx builder is left stopped. A failed deployment skips
cleanup, and a cleanup failure is reported without rolling back a healthy release.
