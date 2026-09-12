#!/usr/bin/env bash
# Выкладка OrbitLink на сервер svo.
#
# Что делает: копирует закоммиченные исходники (git archive HEAD) в
# /opt/orbitlink, собирает образы на сервере, поднимает контейнеры
# и проверяет, что сервис отвечает.
#
# Чего НЕ делает: не трогает /etc/caddy/Caddyfile. Прокси общий для всех
# проектов сервера, его правка — отдельный ручной шаг, см. README, раздел
# «Развёртывание на сервере».
#
# Запуск из корня репозитория:  bash deploy/deploy-svo.sh

set -euo pipefail

HOST="${DEPLOY_HOST:-svo}"
DEST="${DEPLOY_DIR:-/opt/orbitlink}"
ENV_FILE="deploy/svo.env"

cd "$(dirname "$0")/.."
[ -f "$ENV_FILE" ] || { echo "нет $ENV_FILE — запускать из репозитория OrbitLink" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

echo "==> каталог $DEST на $HOST"
ssh "$HOST" "sudo mkdir -p '$DEST' && sudo chown \"\$(id -un)\" '$DEST'"

echo "==> копирование исходников"
git archive --format=tar HEAD | ssh "$HOST" "tar -xf - -C '$DEST'"

COMPOSE="docker compose --env-file deploy/svo.env -f deploy/docker-compose.yml"

echo "==> сборка образов (по одному, сервер общий)"
ssh "$HOST" "cd '$DEST' && $COMPOSE build"

echo "==> запуск"
ssh "$HOST" "cd '$DEST' && $COMPOSE up -d"

echo "==> проверка живости"
for i in $(seq 1 30); do
  if ssh "$HOST" "curl -fsS -m 5 http://127.0.0.1:${FRONTEND_PORT}/api/selftest" >/tmp/orbitlink-selftest.json 2>/dev/null; then
    python3 -c "import json;d=json.load(open('/tmp/orbitlink-selftest.json'));print('   сверка с эталоном: ok =',d['ok'],'| проверок',len(d['checks']))"
    ssh "$HOST" "cd '$DEST' && $COMPOSE ps"
    echo "==> готово: интерфейс на 127.0.0.1:${FRONTEND_PORT} сервера $HOST"
    echo "    наружу — после добавления deploy/Caddyfile.orbitlink в системный Caddy"
    exit 0
  fi
  sleep 3
done
echo "сервис не ответил за 90 секунд, журнал:" >&2
ssh "$HOST" "cd '$DEST' && $COMPOSE logs --tail 60" >&2
exit 1
