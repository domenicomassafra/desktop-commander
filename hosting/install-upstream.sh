#!/bin/sh
# Install the official pinned npm package without changing the active service.
set -eu
version=0.3.1
prefix="$HOME/.local/opt/desktop-commander/upstream-$version"
package="$prefix/node_modules/@wonderwhy-er/desktop-commander"
if [ ! -f "$package/dist/index.js" ]; then
    mkdir -p "$prefix"
    DESKTOP_COMMANDER_DISABLE_TELEMETRY=1 DC_FLAG_URL='data:application/json,{"flags":{}}' \
        npm install --prefix "$prefix" --save-exact --omit=dev --no-audit --no-fund \
        "@wonderwhy-er/desktop-commander@$version"
fi
node -e 'if (require(process.argv[1]).version !== process.argv[2]) process.exit(1)' \
    "$package/package.json" "$version"
test -s "$package/dist/index.js"
printf '%s\n' "$package"
