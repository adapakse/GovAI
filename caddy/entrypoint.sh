#!/bin/sh
set -e

if [ -n "$DOMAIN_NAME" ]; then
  sed "s|{{ADDRESS}}|$DOMAIN_NAME|" /etc/caddy/Caddyfile.domain.template > /etc/caddy/Caddyfile
else
  cp /etc/caddy/Caddyfile.internal.template /etc/caddy/Caddyfile
fi

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
