#!/bin/sh
set -e

# website-src jest zamontowane :ro — kopiujemy do zapisywalnej ścieżki, żeby
# móc podstawić {{ADDRESS}} (canonical/OG/sitemap) bez modyfikowania bind-mounta.
mkdir -p /srv/website
cp -r /srv/website-src/. /srv/website/

if [ -n "$DOMAIN_NAME" ]; then
  sed "s|{{ADDRESS}}|$DOMAIN_NAME|" /etc/caddy/Caddyfile.domain.template > /etc/caddy/Caddyfile
  find /srv/website -type f \( -name '*.html' -o -name '*.xml' -o -name '*.txt' \) \
    -exec sed -i "s|{{ADDRESS}}|$DOMAIN_NAME|" {} +
else
  cp /etc/caddy/Caddyfile.internal.template /etc/caddy/Caddyfile
fi

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
