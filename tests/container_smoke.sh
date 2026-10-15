#!/usr/bin/env bash
# Starts only a separate test project and deletes its containers and test volume.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
: "${VORUM_IMAGE:?Set VORUM_IMAGE to a locally built image, e.g. vorum:ci}"
export COMPOSE_PROJECT_NAME="vorum-smoke-$$-$RANDOM"
export VORUM_BIND=127.0.0.1 VORUM_PORT=0 COOKIE_SECURE=0
compose=(docker compose -f compose.release.yaml)
cleanup() {
  result=$?
  if [[ $result -ne 0 ]]; then
    "${compose[@]}" logs --no-color || true
  fi
  "${compose[@]}" down --volumes --remove-orphans || true
  exit "$result"
}
trap cleanup EXIT
"${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 120
"${compose[@]}" exec -T vorum python - <<'PY'
import os
from pathlib import Path
from urllib.request import urlopen

assert os.getuid() != 0, 'Web server must run without root privileges'
assert Path('/app/LICENSE').is_file(), 'MIT license must ship in the image'
with urlopen('http://127.0.0.1:8000/', timeout=10) as response:
    assert response.status == 200
    assert b'Vorum' in response.read()
Path('/app/data/.container-smoke').write_text('shared-volume')
PY
"${compose[@]}" exec -T notification-worker python - <<'PY'
import os
import sqlite3
from pathlib import Path

assert os.getuid() != 0, 'Worker must run without root privileges'
assert Path('/app/data/.container-smoke').read_text() == 'shared-volume'
with sqlite3.connect('/app/data/vorum.sqlite3') as connection:
    assert connection.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone()
PY
# Recreate both containers to ensure data survives replacement, as on updates.
"${compose[@]}" up -d --force-recreate --no-build --pull never --wait --wait-timeout 120
"${compose[@]}" exec -T vorum python -c "from pathlib import Path; assert Path('/app/data/.container-smoke').read_text() == 'shared-volume'"
"${compose[@]}" exec -T notification-worker python -c "from pathlib import Path; assert Path('/app/data/.container-smoke').read_text() == 'shared-volume'"
printf '%s\n' 'Container smoke test passed.'
