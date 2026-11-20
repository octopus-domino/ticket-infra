# Проверки перед деплоем и очистка сервера

Команды выполняются на сервере из общего каталога четырёх репозиториев. SSH использует ключ из локальной конфигурации оператора.

- `bash ticket-infra/scripts/check-host-cleanup.sh` показывает свободное место, размеры кеша и логов и образы CoDoc, доступные для очистки.
- `bash ticket-infra/scripts/check-host-cleanup.sh --apply` под блокировкой деплоя удаляет старые образы с тегами `before-*` и очищает кеш пакетов APT. Скрипт сохраняет образы контейнеров, ссылки из `previous-image.txt`, `latest` и самый новый образ с тегом `before-*`. Ротированный `syslog.1` сжимается. Удаление конкретных архивов H2 и старых дампов в этот скрипт не входит.
- `bash ticket-infra/scripts/check-deploy-config.sh` проверяет конфигурацию деплоя. `bash ticket-infra/scripts/check-deploy-entrypoint.sh` проверяет диспетчеризацию в изолированном примере на машине с Bash.
- `bash ticket-infra/deploy.sh` обновляет четыре репозитория, создаёт дамп PostgreSQL, собирает образы с ограничениями из RESOURCE-BUDGET.md и проверяет запуск сервисов.
- `python3 ticket-infra/scripts/check_runtime_api.py --base-url https://www.codoc.site` проверяет публичный API тем и пеших маршрутов.

Отдельное описание MCP Островка находится в [mcp/ostrovok/README.md](../mcp/ostrovok/README.md).
