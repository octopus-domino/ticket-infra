# Build and runtime data

Dockerfile собирается из родительской папки трёх репозиториев:

```sh
docker build -f ticket-infra/Dockerfile -t ticket-editor:stabilized .
```

Frontend использует `npm ci`, проверки типов/архитектуры/lint и tests перед build. Backend использует `mvn clean verify`, включая интеграционные тесты. nginx body limit согласован с backend: 20 MB.

Образ объявляет `/app/data` как volume. При запуске задайте явный persistent volume и `SPRING_PROFILES_ACTIVE=prod`, JWT/OAuth/SMTP credentials через окружение. Production profile валидирует существующую бизнес-схему H2; инструкции и ограничение первого развёртывания находятся в `ticket-pdf/STABILIZATION.md`. Секреты и DB не должны попадать в образ или Git.

Перед обновлением остановите контейнер и скопируйте весь volume. Восстановление сначала проверяйте в отдельном пустом volume. Не восстанавливайте поверх работающей H2. Generation metadata, файлы и email ledger должны восстанавливаться согласованно с DB.

При использовании Sentry задайте build-time `VITE_SENTRY_DSN` и разрешите конкретный origin в nginx `connect-src` либо используйте собственный tunnel. Текущая CSP не разрешает произвольные telemetry destinations.

Docker CLI установлен, но daemon в рабочем окружении не запущен: полный образ и nginx runtime пока не проверены. Отдельные frontend build и Maven verify проверяются независимо. Deployment не выполнялся.
