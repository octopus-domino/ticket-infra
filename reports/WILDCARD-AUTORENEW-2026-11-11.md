# Wildcard и автопродление

Проверено на действующем сервере 11 ноября 2026 года.

- DNS остаётся на `ns1.hosting.reg.ru` и `ns2.hosting.reg.ru`.
- Wildcard A-запись направляет поддомены на сервер Codoc; `invite.codoc.site` и `proposals.codoc.site` отвечают по HTTPS.
- Сертификат `/etc/letsencrypt/live/codoc-wildcard` покрывает `codoc.site` и `*.codoc.site`, срок действия — до 9 февраля 2027 года.
- Настроены DNS hooks ISPmanager: создают только проверочные TXT-записи `_acme-challenge.codoc.site` и удаляют только собственные значения.
- Данные API хранятся только на сервере в root-файле с правами 600. Репозитории и отчёты не содержат их значений.
- `certbot reconfigure` успешно проверил новый способ продления. Затем отдельный `certbot renew --dry-run --cert-name codoc-wildcard` завершился: **all simulated renewals succeeded**.
- После очистки API вернул исходное количество DNS-записей: 21.
- `certbot.timer` включён. Deploy hook проверяет конфигурацию Nginx и перезагружает её после обновления wildcard-сертификата.

Первое выполнение ожидало истечения старого DNS-кеша. Hooks проверяют авторитативные серверы и публичные резолверы, затем выдерживают TTL. Последующие продления выполняются автоматически.

Инструкция: [REG-RU-WILDCARD.md](../REG-RU-WILDCARD.md).
