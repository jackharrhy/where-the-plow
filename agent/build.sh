#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VERSION="dev-$(date -u +%Y.%m.%d)-$(git rev-parse --short HEAD)"

go build -trimpath -ldflags "-s -w -X main.version=${VERSION}" -o plow-agent .

echo "Built plow-agent ${VERSION}"
