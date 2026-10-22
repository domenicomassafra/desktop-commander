#!/bin/sh
# Runtime-only build: declaration emit is irrelevant to hosting and Bun's nested
# arg dependency otherwise triggers upstream TypeScript TS2742.
set -eu
node node_modules/typescript/bin/tsc --declaration false
cp setup-claude-server.js uninstall-claude-server.js track-installation.js dist/
mkdir -p dist/data dist/remote-device/scripts
cp src/data/onboarding-prompts.json dist/data/
cp src/remote-device/scripts/blocking-offline-update.js dist/remote-device/scripts/
node scripts/build-ui-runtime.cjs
