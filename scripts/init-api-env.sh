#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -e .env ]; then
  printf '%s\n' '.env already exists; it was not changed.' >&2
  exit 1
fi
frontend=${1:-https://docs.example.ru}
public_api=${2:-https://api.example.ru/client-api}
case "$frontend:$public_api" in *'
'*) printf '%s\n' 'URLs must not contain line breaks.' >&2; exit 1;; esac
case "$frontend" in https://*) ;; *) printf '%s\n' 'Frontend URL must use HTTPS.' >&2; exit 1;; esac
case "$public_api" in https://*/client-api) ;; *) printf '%s\n' 'API URL must use HTTPS and end in /client-api.' >&2; exit 1;; esac
umask 077
{
  printf 'JWT_SECRET=%s\n' "$(openssl rand -hex 32)"
  printf 'APP_SECRETS_ENCRYPTION_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'TYK_ADMIN_SECRET=%s\n' "$(openssl rand -hex 32)"
  printf 'REDIS_PASSWORD=%s\n' "$(openssl rand -hex 32)"
  printf 'APP_FRONTEND_URL=%s\nCLIENT_API_PUBLIC_URL=%s\n' "$frontend" "$public_api"
  printf 'DB_SCHEMA_MODE=validate\nCONNECTOR_ALLOWED_ORIGINS=\n'
} > .env
printf '%s\n' '.env created with independent secrets and owner-only permissions. Keep a secure backup.'
