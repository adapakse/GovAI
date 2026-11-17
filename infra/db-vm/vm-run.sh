#!/usr/bin/env bash
# Uruchamia skrypt bash na VM vm-govai-data przez `az vm run-command invoke` (bootstrap, workflowy GitHub).
#
#   vm-run.sh '<polecenia bash>'      albo      vm-run.sh @plik.sh
#
# run-command nie przekazuje kodu wyjścia skryptu i zwraca tylko ostatnie ~4 KB stdout/stderr —
# sukces = linia GOVAI_RESULT=OK w wyjściu (wypisują ją govai-data.sh i restore.sh).
# Wymaga zalogowanego az; subskrypcja/grupa/VM nadpisywalne zmiennymi GOVAI_*.
set -euo pipefail
export MSYS_NO_PATHCONV=1
SUB=${GOVAI_SUBSCRIPTION:-5e23c5f2-d269-41d3-b558-7d65dad68f1e}
RG=${GOVAI_RG:-rg-govai}
VM=${GOVAI_DATA_VM:-vm-govai-data}

[ $# -eq 1 ] || { sed -n '2,8p' "$0"; exit 2; }
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
case "$1" in
  @*) cp "${1#@}" "$tmp" ;;
  *) printf '%s\n' "$1" > "$tmp" ;;
esac

# --scripts @plik: treść z pliku (na Windows az.cmd ma limit długości wiersza poleceń);
# w Git Bash az (Python dla Windows) potrzebuje ścieżki windowsowej.
script_path=$tmp
command -v cygpath >/dev/null 2>&1 && script_path=$(cygpath -w "$tmp")
out=$(az vm run-command invoke --subscription "$SUB" -g "$RG" -n "$VM" --command-id RunShellScript \
  --scripts @"$script_path" --query 'value[0].message' -o tsv)
printf '%s\n' "$out"
grep -q 'GOVAI_RESULT=OK' <<<"$out"
