# Caddy z modułem DNS Cloudflare — potrzebny do certyfikatu wildcard
# *.<DOMAIN_NAME> (subdomeny organizacji, wyzwanie ACME DNS-01).
FROM caddy:2-builder-alpine AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
