#!/usr/bin/env bash
# Export the snapshot and deploy web/ to Vercel. Schedule every 2 h, e.g. crontab:
#   0 */2 * * * cd /path/to/jobpipeline && ./scripts/publish_web.sh >> /tmp/publish_web.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
python -m jobpipeline.export --out web/data.json
npx --yes vercel@latest deploy --prod --yes --token "$VERCEL_TOKEN" web/
