#!/bin/bash
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

groupadd -o -g "$PGID" booksarr 2>/dev/null || true
useradd -o -u "$PUID" -g "$PGID" -d /config -s /bin/bash booksarr 2>/dev/null || true

chown -R "$PUID:$PGID" /config

exec gosu booksarr "$@"
