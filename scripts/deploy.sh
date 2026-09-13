#!/usr/bin/env bash
# deploy.sh — put Home Assistant package files on vesta and reload, from this checkout (card #299).
#
#   scripts/deploy.sh                          # every packages/*.yaml
#   scripts/deploy.sh pomona_schedule          # one package (name or path)
#   scripts/deploy.sh --check                  # only compare the # version: headers: git vs vesta
#   scripts/deploy.sh --restart pomona_*       # full core restart instead of reload_all
#
# Access:
#   ssh, key-based, to the HAOS SSH add-on:   VESTA=admin@vesta.local (default)   VESTA_CONFIG=/config (default)
#     Files travel over the ssh SHELL channel into `sudo tee` — NOT scp/sftp: on the add-on the sftp
#     subsystem lands in a different filesystem view and `scp` "succeeds" without the file ever
#     reaching /config, and /config is root-owned while the ssh user is `admin` (passwordless sudo;
#     lessons of 2026-09-13). The written header is read back as proof.
#   HA REST for the config check + reload:   export HA_TOKEN=<long-lived access token>   HA_URL=http://vesta.local:8123
#     (Profile → Security → Long-lived access tokens). Read from the environment only, never printed
#     or written. Without it the files are still copied, but the check and the reload cannot run from
#     here (the add-on's `ha` CLI has no supervisor token in an ssh session, sudo or not): restart
#     Home Assistant from Settings → System → Restart, or export the token and rerun.
set -euo pipefail
VESTA="${VESTA:-admin@vesta.local}"
VESTA_CONFIG="${VESTA_CONFIG:-/config}"
HA_URL="${HA_URL:-http://vesta.local:8123}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 "$VESTA")

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
remote_ver() {  # <absent> = no such file on vesta; <no header> = file without a # version: line
  local p="$VESTA_CONFIG/packages/$(basename "$1")"
  "${SSH[@]}" "if [ -f '$p' ]; then v=\$(sed -n 's/^# version: *//p' '$p' | head -1); echo \"\${v:-<no header>}\"; else echo '<absent>'; fi" 2>/dev/null || echo "<ssh failed>"
}

echo "vesta: $VESTA  config: $VESTA_CONFIG  branch: $(git branch --show-current)"
printf '%-28s %-10s %-12s\n' package git vesta
for f in "${files[@]}"; do printf '%-28s %-10s %-12s\n' "$(basename "$f")" "$(ver "$f")" "$(remote_ver "$f")"; done
[ "$mode" = check ] && exit 0

for f in "${files[@]}"; do
  git diff --quiet -- "$f" && git diff --quiet --cached -- "$f" || { echo "refusing: $f has uncommitted changes — commit (and bump # version:) first" >&2; exit 1; }
  [ -n "$(ver "$f")" ] || { echo "refusing: $f has no '# version:' header" >&2; exit 1; }
done

echo "copying ${#files[@]} file(s) to $VESTA:$VESTA_CONFIG/packages/ (ssh shell channel, sudo tee)"
for f in "${files[@]}"; do
  p="$VESTA_CONFIG/packages/$(basename "$f")"
  "${SSH[@]}" "sudo -n tee '$p.tmp' >/dev/null && sudo -n mv -f '$p.tmp' '$p' && sudo -n chmod 644 '$p'" < "$f"
  got="$(remote_ver "$f")"
  [ "$got" = "$(ver "$f")" ] || { echo "verify FAILED for $(basename "$f"): vesta has '$got'" >&2; exit 1; }
  echo "  $(basename "$f") -> $got"
done

if [ -z "${HA_TOKEN:-}" ]; then
  echo "files are on vesta. No HA_TOKEN in the environment: cannot check the config or reload from here."
  echo "Restart Home Assistant (Settings → System → Restart), or: export HA_TOKEN=<long-lived token> and rerun with the same arguments."
  exit 0
fi
api() { curl -sS -X POST -H "Authorization: Bearer $HA_TOKEN" -H 'Content-Type: application/json' "$HA_URL/api/$1" -d "${2:-{\}}"; }
res="$(api config/core/check_config)"
echo "$res" | grep -q '"result": *"valid"' || { echo "config check FAILED on vesta: $res" >&2; echo "the files stay as copied — fix and redeploy, or restore the previous version" >&2; exit 1; }
echo "config valid"
if [ "$mode" = restart ]; then api services/homeassistant/restart '{}' >/dev/null; echo "restart requested"
else api services/homeassistant/reload_all '{}' >/dev/null; echo "reload_all requested"; fi
echo "deployed:"
for f in "${files[@]}"; do printf '  %-26s %s\n' "$(basename "$f")" "$(remote_ver "$f")"; done
