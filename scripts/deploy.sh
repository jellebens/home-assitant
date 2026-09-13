#!/usr/bin/env bash
# deploy.sh — put Home Assistant package files on vesta and reload, from this checkout (card #299).
#
#   scripts/deploy.sh                          # every packages/*.yaml
#   scripts/deploy.sh pomona_schedule          # one package (name or path)
#   scripts/deploy.sh --check                  # only compare the # version: headers: git vs vesta
#   scripts/deploy.sh --restart pomona_*       # full `ha core restart` instead of reload_all
#
# Access — one of:
#   ssh to vesta (HAOS "Advanced SSH & Web Terminal" add-on or the SSH add-on; key-based):
#     VESTA=root@vesta.local         (default)      VESTA_CONFIG=/config   (default)
#   HA REST for the reload (optional, avoids the full restart): export HA_TOKEN=<long-lived token>
#     HA_URL=http://vesta.local:8123 (default). The token is read from the environment only; never
#     printed, never written. Without it the script uses `ha core check` + reload via the CLI, or
#     `ha core restart` with --restart.
#
# What it does: shows the local vs deployed `# version:` per file, refuses a dirty local file,
# copies the files with scp into $VESTA_CONFIG/packages/, validates the config on vesta, reloads
# (homeassistant.reload_all) or restarts, and prints the deployed headers again as proof.
set -euo pipefail
VESTA="${VESTA:-root@vesta.local}"
VESTA_CONFIG="${VESTA_CONFIG:-/config}"
HA_URL="${HA_URL:-http://vesta.local:8123}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

mode=deploy; files=()
for a in "$@"; do
  case "$a" in
    --check) mode=check ;;
    --restart) mode=restart ;;
    *) f="$a"; [[ "$f" == packages/* ]] || f="packages/${f%.yaml}.yaml"; files+=("$f") ;;
  esac
done
[ ${#files[@]} -gt 0 ] || files=(packages/*.yaml)
for f in "${files[@]}"; do [ -f "$f" ] || { echo "no such package: $f" >&2; exit 1; }; done

ver() { sed -n 's/^# version: *//p' "$1" | head -1; }
remote_ver() { ssh -o BatchMode=yes -o ConnectTimeout=8 "$VESTA" "sed -n 's/^# version: *//p' '$VESTA_CONFIG/packages/$(basename "$1")' 2>/dev/null | head -1" 2>/dev/null || true; }

echo "vesta: $VESTA  config: $VESTA_CONFIG  branch: $(git branch --show-current)"
printf '%-28s %-10s %-10s\n' package git vesta
for f in "${files[@]}"; do rv="$(remote_ver "$f")"; printf '%-28s %-10s %-10s\n' "$(basename "$f")" "$(ver "$f")" "${rv:-<absent>}"; done
[ "$mode" = check ] && exit 0

for f in "${files[@]}"; do
  git diff --quiet -- "$f" && git diff --quiet --cached -- "$f" || { echo "refusing: $f has uncommitted changes — commit (and bump # version:) first" >&2; exit 1; }
  [ -n "$(ver "$f")" ] || { echo "refusing: $f has no '# version:' header" >&2; exit 1; }
done

echo "copying ${#files[@]} file(s) to $VESTA:$VESTA_CONFIG/packages/"
scp -q "${files[@]}" "$VESTA:$VESTA_CONFIG/packages/"

if [ -n "${HA_TOKEN:-}" ]; then
  # validate, then reload everything that packages can define (automation, template, mqtt, ...)
  res="$(curl -sS -X POST -H "Authorization: Bearer $HA_TOKEN" -H 'Content-Type: application/json' "$HA_URL/api/config/core/check_config")"
  echo "$res" | grep -q '"result": *"valid"' || { echo "config check FAILED on vesta: $res" >&2; exit 1; }
  echo "config valid"
  if [ "$mode" = restart ]; then
    curl -sS -o /dev/null -X POST -H "Authorization: Bearer $HA_TOKEN" -H 'Content-Type: application/json' "$HA_URL/api/services/homeassistant/restart" -d '{}'
    echo "restart requested"
  else
    curl -sS -o /dev/null -X POST -H "Authorization: Bearer $HA_TOKEN" -H 'Content-Type: application/json' "$HA_URL/api/services/homeassistant/reload_all" -d '{}'
    echo "reload_all requested"
  fi
else
  ssh -o BatchMode=yes "$VESTA" 'ha core check' || { echo "config check FAILED on vesta (ha core check)" >&2; exit 1; }
  echo "config valid"
  if [ "$mode" = restart ]; then ssh -o BatchMode=yes "$VESTA" 'ha core restart' && echo "restart requested"
  else
    # no token: the HA CLI has no reload_all; a restart is the safe, complete reload
    echo "no HA_TOKEN in the environment: restarting core (export HA_TOKEN for a reload_all instead)"
    ssh -o BatchMode=yes "$VESTA" 'ha core restart' && echo "restart requested"
  fi
fi

echo "deployed:"
for f in "${files[@]}"; do printf '  %-26s %s\n' "$(basename "$f")" "$(remote_ver "$f")"; done
