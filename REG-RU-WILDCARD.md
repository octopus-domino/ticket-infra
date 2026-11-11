# Wildcard с DNS REG.RU и панелью ISPmanager

На действующем сервере сертификат уже выпущен и подключён, A-запись `*` создана.
`https://invite.codoc.site/` и `https://proposals.codoc.site/` проверены через публичный DNS.
Для автопродления осталось подтвердить доступ к API панели хостинга.

## Данные входа

Используется панель `https://server67.hosting.reg.ru:1500/ispmgr`, зона `codoc.site`.
SSO-переход из REG.RU не является постоянным API-доступом.
В личном кабинете откройте услугу хостинга → «Доступы»: основной логин обычно имеет вид `u1234567`.
Пароль основного FTP-аккаунта используется также для входа в ISPmanager.
Не меняйте его без необходимости: сброс изменяет доступ и FTP, и панели.
Справка провайдера: https://help.reg.ru/support/hosting/dostupy-i-podklyucheniye-panel-upravleniya-ftp-ssh/rabota-po-ftp-akkaunty-i-paroli

В своей SSH-сессии на сервере выполните:

```bash
sudo python3 /usr/local/lib/codoc/configure-ispmanager.py
```

Введите логин и пароль панели по приглашениям. Пароль скрыт, не попадает в историю shell
или аргументы процесса. HTTPS-сертификат панели проверяется; перенаправления запрещены.
Помощник выполняет запрос списка записей без изменений и только после его успеха
создаёт `/etc/letsencrypt/codoc-ispmanager.json`: владелец root, права 600.
Пароль от личного кабинета REG.RU здесь не используется.

Исходники: `scripts/configure-ispmanager-credentials.py`, `scripts/ispmanager-dns.py`.
Они установлены в `/usr/local/lib/codoc/`. Для новой установки их нужно скопировать туда
от root с правами 750; каталог должен принадлежать root.

## Проверка и включение после сохранения данных

```bash
sudo /usr/local/lib/codoc/ispmanager-dns.py check
sudo certbot reconfigure --cert-name codoc-wildcard --non-interactive \
  --manual-auth-hook '/usr/local/lib/codoc/ispmanager-dns.py auth' \
  --manual-cleanup-hook '/usr/local/lib/codoc/ispmanager-dns.py cleanup'
sudo certbot renew --dry-run --cert-name codoc-wildcard
sudo systemctl enable --now certbot.timer
```

`reconfigure` в Certbot 2.9 проверяет изменение через тестовое продление.
Не считать настройку завершённой до успешной проверки API и тестового продления.
Если провайдер ограничивает `authinfo` по IP, разрешить адрес сервера CoDoc.

Hook создаёт только TXT `_acme-challenge.codoc.site`, ожидает её появления на обоих
авторитетных DNS-серверах и Google DNS, затем удаляет только созданное им значение
по точному `rkey`. Другие TXT и DNS-записи сохраняются. Предсуществовавшее идентичное
значение не удаляется. Проверяются также DNS Cloudflare; перед валидацией проходит
ещё один TTL (300 секунд). Ожидание ограничено двумя часами: первая настройка
может ждать истечения часового кеша старой ручной TXT-записи.

Установленный deploy-hook `/etc/letsencrypt/renewal-hooks/deploy/codoc-wildcard-nginx.sh`
после успешного продления проверяет конфигурацию Nginx и выполняет reload.
Один `certbot.timer` без рабочих DNS hooks не продлевает вручную выпущенный wildcard.

API описан производителем: https://www.ispmanager.ru/docs/ispmanager/ispmanager-api
и https://www.ispmanager.ru/docs/ispmanager/vzaimodejstvie-cherez-api
