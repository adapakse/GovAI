#!/bin/sh
# Start govai-edge (Azure Container Apps): renderuje Caddyfile.edge i podstawia
# {{ADDRESS}} w landingu (canonical/OG/sitemap), jak caddy/entrypoint.sh.
#
# Zmienne:
#   API_UPSTREAM, GATEWAY_UPSTREAM, FRONTEND_UPSTREAM — wymagane (np. http://govai-api-int)
#   SITE_HOSTS  — hosty landingu, spacje lub przecinki (np. "govai.pl www.govai.pl");
#                 www.* → 301 na pierwszy host bez www; puste = bez landingu
#   DOMAIN_NAME — podstawiane za {{ADDRESS}} w plikach website (np. govai.pl)
set -e

for v in API_UPSTREAM GATEWAY_UPSTREAM FRONTEND_UPSTREAM; do
  eval "val=\${$v:-}"
  if [ -z "$val" ]; then
    echo "edge: brak zmiennej $v" >&2
    exit 1
  fi
done

# Landing — kopia z obrazu do zapisywalnej ścieżki (podstawienie {{ADDRESS}}).
rm -rf /srv/website
mkdir -p /srv/website
cp -r /srv/website-src/. /srv/website/
if [ -n "$DOMAIN_NAME" ]; then
  find /srv/website -type f \( -name '*.html' -o -name '*.xml' -o -name '*.txt' \) \
    -exec sed -i "s|{{ADDRESS}}|$DOMAIN_NAME|g" {} +
fi

hosts=$(echo "${SITE_HOSTS:-}" | tr ',' ' ' | tr 'A-Z' 'a-z')
primary=""
www_hosts=""
site_hosts=""
for h in $hosts; do
  case "$h" in
    www.*) www_hosts="$www_hosts $h" ;;
    *) site_hosts="$site_hosts $h"; [ -z "$primary" ] && primary="$h" ;;
  esac
done
# Same hosty www (bez hosta głównego) — serwujemy landing bez przekierowania.
if [ -z "$primary" ] && [ -n "$www_hosts" ]; then
  site_hosts="$www_hosts"
  www_hosts=""
fi

block=/tmp/site-block.caddy
: > "$block"
if [ -n "$www_hosts" ]; then
  cat >> "$block" <<EOF
	# www → host główny landingu
	@site_www {
		host$www_hosts
		not path /healthz
	}
	handle @site_www {
		redir https://$primary{uri} permanent
	}

EOF
fi
if [ -n "$site_hosts" ]; then
  cat >> "$block" <<EOF
	# Landing + blog — statyczne pliki z website/ (jak Caddyfile.domain.template)
	@site {
		host$site_hosts
		not path /healthz
	}
	handle @site {
		root * /srv/website
		try_files {path} {path}.html
		file_server
	}
EOF
fi

awk -v blockfile="$block" '
  $0 ~ /^\{\{SITE_BLOCK\}\}$/ { while ((getline line < blockfile) > 0) print line; next }
  { print }
' /etc/caddy/Caddyfile.edge > /etc/caddy/Caddyfile

echo "edge: landing:${site_hosts:- (brak)}${www_hosts:+, przekierowanie www:$www_hosts}"
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
