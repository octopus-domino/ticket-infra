# Build and runtime data

Dockerfile собирается из родительской папки трёх репозиториев:

```sh
DOCKER_BUILDKIT=1 docker build -f ticket-infra/Dockerfile -t ticket-editor:stabilized .
```

Обычный legacy builder не поддерживает `RUN --mount`. Строка `# syntax=...` внутри Dockerfile сама по себе BuildKit не включает. Если сборка останавливается с `the --mount option requires BuildKit`, перезапустите её командой выше.

Для запуска из любой папки добавлены скрипты, включающие BuildKit и задающие правильный build context:

```sh
bash ticket-infra/build.sh
# Дополнительные параметры Docker передаются дальше:
bash ticket-infra/build.sh --build-arg VITE_YANDEX_METRIKA_ID=114057241
```

PowerShell:

```powershell
$env:DOCKER_BUILDKIT = '1'
docker build -f ticket-infra/Dockerfile -t ticket-editor:stabilized .
# Или скрипт (временно включает BuildKit и возвращает код завершения Docker):
.\ticket-infra\build.ps1
```

Если Docker сообщает, что BuildKit включён, но компонент Buildx отсутствует, установите совместимый с вашим Docker плагин Buildx. На актуальном Docker также можно использовать `docker buildx build --load -f ticket-infra/Dockerfile -t ticket-editor:stabilized .`. Для этих Linux-образов Docker Desktop должен работать в режиме Linux containers.

## Кеш зависимостей при сборке

Dockerfile использует BuildKit (`# syntax=docker/dockerfile:1`). Между сборками сохраняются два кеша builder:

- `codoc-npm` → `/root/.npm`, кеш скачанных npm-пакетов; `npm ci --prefer-offline` сохраняет проверку lock-файла и воспроизводимую установку.
- `codoc-maven` → `/root/.m2/repository`, один кеш для `dependency:go-offline` и `clean verify`. Изменение Java-кода не требует повторного скачивания всех зависимостей.

Для обоих кешей задано `sharing=locked`, чтобы параллельные сборки не писали в них одновременно. Кеши принадлежат Docker builder, не попадают в итоговый образ и не требуют runtime-volumes у контейнера приложения. Они работают при повторных сборках тем же builder; после очистки build cache или на новом сервере зависимости придётся скачать заново. В GitHub Actions кеши Maven и npm уже включены через `setup-java` и `setup-node`.

`Dockerfile.dockerignore` ограничивает build context исходниками трёх проектов и исключает `node_modules`, `target`, `dist`, рабочие БД, локальные env-файлы и Git. Это также предотвращает подмену Linux-зависимостей файлами `node_modules` с Windows при `COPY`.

Для старых установок Docker включите BuildKit: `DOCKER_BUILDKIT=1 docker build -f ticket-infra/Dockerfile -t ticket-editor:stabilized .`. Gradle в этих проектах не используется; если появится Gradle-stage, его кеш нужно монтировать в Gradle User Home (`/root/.gradle` для root или `/home/gradle/.gradle` для пользователя gradle).

Пример для будущего stage с пользователем `gradle`:

```dockerfile
RUN --mount=type=cache,id=codoc-gradle,target=/home/gradle/.gradle,uid=1000,gid=1000,sharing=locked \
    ./gradlew --no-daemon --build-cache build
```

Frontend использует `npm ci`, проверки типов/архитектуры/lint и tests перед build. Backend использует `mvn clean verify`, включая интеграционные тесты. nginx body limit согласован с backend: 20 MB.

Образ объявляет `/app/data` как volume. При запуске задайте явный persistent volume и `SPRING_PROFILES_ACTIVE=prod`, JWT/OAuth/SMTP credentials через окружение. Production profile валидирует существующую бизнес-схему H2; инструкции и ограничение первого развёртывания находятся в `ticket-pdf/STABILIZATION.md`. Секреты и DB не должны попадать в образ или Git.

Перед обновлением остановите контейнер и скопируйте весь volume. Восстановление сначала проверяйте в отдельном пустом volume. Не восстанавливайте поверх работающей H2. Generation metadata, файлы и email ledger должны восстанавливаться согласованно с DB.

При использовании Sentry задайте build-time `VITE_SENTRY_DSN` и разрешите конкретный origin в nginx `connect-src` либо используйте собственный tunnel. Текущая CSP не разрешает произвольные telemetry destinations.

## Метрика блокируется CSP

В актуальном `nginx.conf` уже разрешены `https://mc.yandex.ru`, `https://mc.yandex.com` и `https://yastatic.net` в `script-src`, а endpoints Метрики — в `connect-src`. В backend и HTML отдельная CSP не задаётся.

Для служебных iframe Метрики в `frame-src` также разрешены `https://mc.yandex.ru`, `https://mc.yandex.com` и `blob:`. Если появляется `Framing 'https://mc.yandex.ru/' violates ... frame-src`, обновите именно эту директиву в активной CSP:

```text
frame-src blob: https://mc.yandex.ru https://mc.yandex.com https://drawio.codoc.site https://forms.yandex.ru https://forms.yandex.com https://cloud.yandex.ru;
```

Если браузер всё ещё сообщает `script-src 'self'`, проверьте **заголовки ответа HTML-документа**, а не `tag.js`, и конфиг работающего Nginx:

```sh
curl -sSI -L https://codoc.site/
docker exec CONTAINER nginx -T
```

`CONTAINER` замените именем контейнера приложения. Для внешнего Nginx на хосте используйте `sudo nginx -T`.

В итоговой политике должны быть, в частности:

```text
script-src 'self' https://mc.yandex.ru https://mc.yandex.com https://yastatic.net;
```

Полную политику, включая `connect-src` и разрешения для Яндекс Форм, берите из `ticket-infra/nginx.conf`. Не заменяйте её одним `script-src` и не добавляйте второй разрешающий заголовок поверх запрещающего: браузер применяет все enforced CSP одновременно. Если старую политику добавляет внешний reverse proxy/CDN, обновите или уберите дублирующий источник там.

Dockerfile кладёт конфиг в `/etc/nginx/http.d/default.conf`. После правки активного конфига проверьте его и перезагрузите Nginx:

```sh
docker exec CONTAINER nginx -t
# Выполняйте reload только после успешной проверки:
docker exec CONTAINER nginx -s reload
```

Если меняли Docker-образ, а не файл работающего контейнера, пересоздайте контейнер из нового образа с прежними runtime-параметрами, секретами и томом данных. Обычный `docker restart` не заменяет образ. Также проверьте, не перекрывает ли конфиг старый bind mount. После исправления очистите кеш HTML на reverse proxy/CDN, если он используется, и обновите страницу.

Источники: [CSP для Метрики](https://yandex.ru/support/metrica/ru/code/install-counter-csp), [совместное применение нескольких CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy).

Docker CLI установлен, но daemon в рабочем окружении не запущен: полный образ и nginx runtime пока не проверены. Отдельные frontend build и Maven verify проверяются независимо. Deployment не выполнялся.
