#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

case "${1:-}" in
  start|stop|restart|status|logs)
    if [[ $# -ne 1 ]]; then
      echo "Aufruf: $0 {start|stop|restart|status|logs}" >&2
      exit 1
    fi
    ;;
  *)
    echo "Aufruf: $0 {start|stop|restart|status|logs}" >&2
    exit 1
    ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker fehlt. Bitte Docker Desktop installieren und starten." >&2
  exit 1
fi

case "$1" in
  start)
    docker compose up --build -d
    echo "Server gestartet: http://localhost:8000"
    ;;
  stop)
    docker compose stop
    echo "Server gestoppt. Gespeicherte Daten bleiben erhalten."
    ;;
  restart)
    docker compose stop
    docker compose up --build -d
    echo "Server neu gestartet: http://localhost:8000"
    ;;
  status)
    docker compose ps -a
    ;;
  logs)
    docker compose logs -f
    ;;
esac
