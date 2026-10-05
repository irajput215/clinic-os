#! /usr/bin/env bash
#
# Regenerate the schema diagrams under docs/reference/schema/ from a migrated database.
#
#   ./scripts/schema-diagram.sh            # regenerate in place
#   ./scripts/schema-diagram.sh --check    # fail if the committed diagrams are stale (CI)
#
# The diagrams are generated, not written. `tbls` reads the live database, so the diagrams describe
# what the database *is* — including what the migrations produced — rather than what the models hope
# they produced. That distinction has already mattered here once: a naming-convention mistake lived in
# the database while the models disagreed, and no diagram would have shown it because none existed.
#
# The database must exist and be migrated first:
#
#   docker compose up -d --wait db
#   (cd backend && uv run alembic upgrade head)
#
# On macOS and Windows, Docker Desktop reaches the host as `host.docker.internal`; on Linux the
# container shares the host's loopback, which is what a CI runner relies on. Override the whole DSN
# with `TBLS_DATABASE_URL` when the database is somewhere else.
#
# No `set -x` here: this script handles a DSN that contains a password.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_relative="docs/reference/schema"
temp_relative=".schema-diagram-check"

# Pinned by tag, matching the image the committed diagrams were generated with. A different tbls
# version can change the generated markdown, which the drift check would report as stale output.
image="ghcr.io/k1low/tbls:v1.96.1"

# `alembic_version` is infrastructure rather than domain schema, and its contents change with every
# migration, so including it would make the committed diagrams churn for no reason.
exclude_table="alembic_version"

# `host.docker.internal` is a Docker Desktop convenience. On Linux — which is what CI runs — the
# container has to share the host's network namespace for `localhost` to mean the runner. The array is
# expanded defensively because an empty array under `set -u` is an error in bash 3.2, which macOS ships.
db_host="host.docker.internal"
network_args=()
if [ "$(uname -s)" = "Linux" ]; then
  db_host="localhost"
  network_args=(--network host)
fi
dsn="${TBLS_DATABASE_URL:-postgresql://postgres:${POSTGRES_PASSWORD:-changethis}@${db_host}:5432/app?sslmode=disable}"

check=false
if [ "${1:-}" = "--check" ]; then
  check=true
elif [ -n "${1:-}" ]; then
  echo "usage: $(basename "$0") [--check]" >&2
  exit 2
fi

target_relative="$output_relative"
if $check; then
  # Generated inside the repo, because that is the directory mounted into the container.
  target_relative="$temp_relative"
  rm -rf "${repo_root:?}/$target_relative"
fi
mkdir -p "$repo_root/$target_relative"

echo "Generating schema diagrams from ${dsn##*@} into $target_relative"
docker run --rm "${network_args[@]+"${network_args[@]}"}" -v "$repo_root:/work" "$image" doc \
  "$dsn" "/work/$target_relative" \
  --er-format mermaid --sort --rm-dist --exclude "$exclude_table"

# tbls also writes schema.json, which embeds the server's full `version()` string — including the
# compiler and architecture it was built with. That differs between a laptop and a CI runner, so it
# can never be part of a drift check. The Mermaid markdown carries no such string.
find "$repo_root/$target_relative" -name 'schema.json' -delete

if $check; then
  if ! diff -ru "$repo_root/$output_relative" "$repo_root/$target_relative" \
      > /tmp/schema-diagram.diff 2>&1; then
    rm -rf "${repo_root:?}/$target_relative"
    echo "::error::docs/reference/schema is out of date. Run ./scripts/schema-diagram.sh and commit the result."
    head -80 /tmp/schema-diagram.diff
    exit 1
  fi
  rm -rf "${repo_root:?}/$target_relative"
  echo "docs/reference/schema is up to date"
else
  echo "Regenerated. Commit docs/reference/schema so the drift check stays green."
fi
