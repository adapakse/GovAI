#!/bin/sh
set -e

if [ -n "$DOMAIN_NAME" ]; then
  ADDRESS="$DOMAIN_NAME"
  TLS_DIRECTIVE=""
else
  ADDRESS=":443"
  TLS_DIRECTIVE="tls internal"
fi

sed -e "s|{{ADDRESS}}|$ADDRESS|" -e "s|{{TLS_DIRECTIVE}}|$TLS_DIRECTIVE|" \
  /etc/caddy/Caddyfile.template > /etc/caddy/Caddyfile

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
