#! /usr/bin/env bash

set -e
set -x

cd backend
FASTAPI_ENV=development uv run python -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../openapi.json
cd ..
cp openapi.json frontend-features/
mv openapi.json frontend/
bun run --filter frontend generate-client
bun run --filter frontend-features generate-client
bun run lint
bun run --filter frontend-features lint
