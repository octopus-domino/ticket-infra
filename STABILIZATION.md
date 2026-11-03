# Build and runtime data

Dockerfile собирается из родительской папки трёх репозиториев:

```sh
docker build -f ticket-infra/Dockerfile -t ticket-editor:stabilized .
```

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

Docker CLI установлен, но daemon в рабочем окружении не запущен: полный образ и nginx runtime пока не проверены. Отдельные frontend build и Maven verify проверяются независимо. Deployment не выполнялся.
