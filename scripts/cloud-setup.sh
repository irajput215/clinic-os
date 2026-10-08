#!/usr/bin/env bash
# Bootstrap a fresh cloud development container (Claude Code on the web, Codespaces, a new VM) the
# way CI bootstraps its runners: a local .env with strong generated secrets, PostgreSQL and Mailpit
# in Docker, the backend migrated, and the frontend dependencies installed.
#
# Idempotent: run it again at any time. It never overwrites an existing .env value and never prints a
# secret. It migrates whatever DATABASE_URL names, which .env.example sets to the local compose
# database: never point a cloud container's .env at a deployed database.
#
#   bash scripts/cloud-setup.sh
#
# See HOW_TO_RUN.md, "Claude Code cloud".
set -euo pipefail

cd "$(dirname "$0")/.."

say() { printf '\n==> %s\n' "$*"; }

# Retry a flaky network step (registry rate limits, a proxy hiccup): 4 tries, 2/4/8 s apart.
retry() {
  local attempt=1 delay=2
  until "$@"; do
    if [ "$attempt" -ge 4 ]; then
      return 1
    fi
    echo "  attempt $attempt failed; retrying in ${delay}s"
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

secret() { python3 -c "import secrets; print(secrets.token_urlsafe(48))"; }

say ".env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  created from .env.example"
fi
# Replace each REPLACE_ME placeholder that is still a placeholder. SECRET_KEY needs 32+ bytes for
# HS256; token_urlsafe(48) is 64 characters.
for key in SECRET_KEY FIRST_SUPERUSER_PASSWORD POSTGRES_PASSWORD; do
  if grep -q "^${key}=REPLACE_ME$" .env; then
    value=$(secret)
    sed -i "s|^${key}=REPLACE_ME$|${key}=${value}|" .env
    echo "  generated ${key}"
  fi
done
sed -i 's|^DOMAIN=REPLACE_ME$|DOMAIN=localhost|' .env

say "Docker"
if ! docker info >/dev/null 2>&1; then
  if command -v dockerd >/dev/null 2>&1; then
    echo "  starting dockerd"
    if [ "$(id -u)" -eq 0 ]; then
      nohup dockerd >/tmp/dockerd.log 2>&1 &
    else
      sudo -n nohup dockerd >/tmp/dockerd.log 2>&1 &
    fi
    for _ in $(seq 1 30); do
      docker info >/dev/null 2>&1 && break
      sleep 1
    done
  fi
fi
docker info >/dev/null 2>&1 || {
  echo "  Docker is not available; start it and run this script again." >&2
  exit 1
}
retry docker compose pull db mailpit
docker compose up -d --wait db mailpit

say "Backend"
(
  cd backend
  retry uv sync
  uv run bash scripts/prestart.sh
)

say "Frontend"
if ! retry bun install; then
  # Some proxies break bun's registry fetch; npm reads the same package.json. Install only: every
  # script still runs with bun.
  echo "  bun install failed; installing with npm instead"
  npm install --no-audit --no-fund
fi

say "Playwright browser"
# Cloud images ship one Chromium build under PLAYWRIGHT_BROWSERS_PATH and forbid downloading another.
# When the pinned @playwright/test expects a newer revision of the headless shell, point that
# revision at the build that is installed. Local-only: nothing in the repository changes.
browsers="${PLAYWRIGHT_BROWSERS_PATH:-}"
manifest=node_modules/playwright-core/browsers.json
if [ -n "$browsers" ] && [ -d "$browsers" ] && [ -f "$manifest" ]; then
  wanted=$(python3 -c "import json,sys; print(next(b['revision'] for b in json.load(open(sys.argv[1]))['browsers'] if b['name'] == 'chromium-headless-shell'))" "$manifest")
  have=$(find "$browsers" -maxdepth 1 -name 'chromium_headless_shell-*' ! -name "*-${wanted}" | sort | tail -1)
  if [ ! -e "$browsers/chromium_headless_shell-${wanted}" ] && [ -n "$have" ] && [ -x "$have/chrome-linux/headless_shell" ]; then
    mkdir -p "$browsers/chromium_headless_shell-${wanted}"
    ln -sfn "$have/chrome-linux" "$browsers/chromium_headless_shell-${wanted}/chrome-headless-shell-linux64"
    ln -sfn headless_shell "$have/chrome-linux/chrome-headless-shell"
    touch "$browsers/chromium_headless_shell-${wanted}/INSTALLATION_COMPLETE" \
      "$browsers/chromium_headless_shell-${wanted}/DEPENDENCIES_VALIDATED"
    echo "  headless shell ${wanted} -> $(basename "$have")"
  else
    echo "  nothing to do"
  fi
else
  echo "  no PLAYWRIGHT_BROWSERS_PATH; run 'cd frontend && bun x playwright install chromium' if needed"
fi

say "Ready"
cat <<'EOF'
  Backend:   cd backend && uv run fastapi dev app/main.py        (http://127.0.0.1:8000)
  Frontend:  bun run dev                                          (http://127.0.0.1:5174)
  Tests:     see HOW_TO_RUN.md section 7 (use a scratch database for pytest and Playwright)
EOF
