#!/usr/bin/env bash
# Przygotowanie VM vm-govai-data (Ubuntu 24.04) — uruchamiane jako root z rozpakowanego pakietu
# w /opt/govai-data: przez cloud-init przy tworzeniu VM i przez `bootstrap.sh datavm` (synchronizacja
# plików przez az vm run-command). Idempotentne.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
DIR=/opt/govai-data
cd "$DIR"
log() { printf '%s [install] %s\n' "$(date '+%F %T')" "$*"; }

# Konfiguracja bez sekretów (z bootstrapu) → /etc/govai/vm.env
install -d -m 0755 /etc/govai
[ -f "$DIR/vm.env" ] && install -m 0644 "$DIR/vm.env" /etc/govai/vm.env
# shellcheck disable=SC1091
. /etc/govai/vm.env
DATA_DIR=${DATA_DIR:-/data}

# ── pakiety: Docker (z repozytorium Ubuntu), jq, curl, openssl, automatyczne aktualizacje ────────
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  log "Instalacja docker.io + docker-compose-v2"
  apt-get update -q
  apt-get install -y -q docker.io docker-compose-v2 jq curl openssl unattended-upgrades
fi
# Rotacja logów kontenerów (domyślnie json-file rośnie bez limitu).
if [ ! -f /etc/docker/daemon.json ]; then
  printf '{\n  "log-driver": "json-file",\n  "log-opts": { "max-size": "20m", "max-file": "5" }\n}\n' > /etc/docker/daemon.json
  systemctl restart docker
fi
systemctl enable --now docker >/dev/null

# Poprawki bezpieczeństwa codziennie; bez automatycznego restartu (restart = przerwa w bazach PROD —
# restart po aktualizacji jądra planuje człowiek, np. przez az vm restart poza godzinami pracy).
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
cat > /etc/apt/apt.conf.d/52govai-unattended <<'EOF'
Unattended-Upgrade::Automatic-Reboot "false";
EOF

# ── dysk danych (LUN 0) → /data ──────────────────────────────────────────────
if ! mountpoint -q "$DATA_DIR"; then
  disk=""
  for c in /dev/disk/azure/data/by-lun/0 /dev/disk/azure/scsi1/lun0; do
    [ -e "$c" ] && { disk=$(readlink -f "$c"); break; }
  done
  [ -n "$disk" ] || { log "BŁĄD: nie znaleziono dysku danych (LUN 0)"; exit 1; }
  if ! blkid "$disk" >/dev/null 2>&1; then
    log "Formatowanie $disk (ext4, etykieta govai-data)"
    mkfs.ext4 -q -L govai-data "$disk"
  fi
  uuid=$(blkid -s UUID -o value "$disk")
  grep -q "UUID=$uuid" /etc/fstab || echo "UUID=$uuid $DATA_DIR ext4 defaults,nofail,discard 0 2" >> /etc/fstab
  mkdir -p "$DATA_DIR"
  mount "$DATA_DIR"
  log "Dysk danych $disk zamontowany w $DATA_DIR"
fi
mkdir -p "$DATA_DIR"/{pg-prod,pg-int,backup-state,backup-work,backups,ssl}
chmod 0700 "$DATA_DIR/backup-work" "$DATA_DIR/ssl"

chmod 0755 "$DIR"/*.sh "$DIR"/initdb/*.sh

# ── systemd: govai-data.service (start usług po restarcie VM) ────────────────
cat > /etc/systemd/system/govai-data.service <<EOF
[Unit]
Description=GovAI — usługi danych (Postgres, Redis, backup)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash $DIR/govai-data.sh boot
# Pierwszy start zwykle wyprzedza propagację ról (Key Vault, ACR) — ponawiamy.
Restart=on-failure
RestartSec=60
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable govai-data.service >/dev/null
# --no-block: cloud-init nie czeka na start (ten może czekać na role managed identity).
systemctl restart --no-block govai-data.service
log "Gotowe — govai-data.service uruchomiona (journalctl -u govai-data -f)"
