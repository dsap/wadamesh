#!/usr/bin/env bash
# wadamesh release: build tagged bins for both touch boards, refresh the
# update-check listing, and publish to the firmware VPS (behind Cloudflare).
#
# Usage:
#   WADAMESH_VPS=user@your-vps WADAMESH_VPS_PATH=/srv/wadamesh/firmware \
#     scripts/release.sh beta_2
#
# The VPS target comes from the environment — never commit it (Cloudflare fronts
# the origin, so the IP isn't needed in the firmware anyway).
set -euo pipefail

TAG="${1:?usage: release.sh <tag>  e.g. beta_2}"
PIO="${PIO:-$HOME/Library/Python/3.9/bin/pio}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/out/firmware"                       # local mirror of the VPS firmware root
REL="$OUT/releases/TOUCH"; LATEST="$OUT/latest"
DEST="${WADAMESH_VPS:-}"; DEST_PATH="${WADAMESH_VPS_PATH:-/srv/wadamesh/firmware}"

# env:binname pairs — plain string form (works on macOS's bash 3.2; no associative arrays)
ENVS="heltec_v4_tft_companion_radio_usb_tcp_touch:wadamesh-heltec-v4-tft LilyGo_TDeck_companion_radio_touch:wadamesh-tdeck"

# 1. Pull the current published tree so the listing stays complete across tags.
if [ -n "$DEST" ]; then
  mkdir -p "$OUT"
  rsync -a "$DEST:$DEST_PATH/" "$OUT/" 2>/dev/null || echo "note: first publish (nothing to pull yet)"
fi
mkdir -p "$REL/$TAG" "$LATEST"

# 2. Build both boards (app + merged), tag + version embedded.
export PLATFORMIO_BUILD_FLAGS="-DFIRMWARE_RELEASE_TAG='\"${TAG}\"' -DFIRMWARE_VERSION='\"wadamesh ${TAG}\"'"
for pair in $ENVS; do
  env="${pair%%:*}"; name="${pair##*:}"
  "$PIO" run -t mergebin -e "$env"
  cp ".pio/build/$env/firmware.bin"        "$REL/$TAG/$name.bin"
  cp ".pio/build/$env/firmware-merged.bin" "$REL/$TAG/$name-merged.bin"
  cp ".pio/build/$env/firmware-merged.bin" "$LATEST/$name-merged.bin"   # rolling latest -> web flasher (standalone)
  cp ".pio/build/$env/firmware.bin"        "$LATEST/$name.bin"          # rolling latest app image -> Launcher path
done

# 3. Regenerate the update-check listing (the firmware scans the body for the
#    highest beta_<N>). JSON array of dir names — GitHub-contents shape.
python3 - "$REL" > "$REL/index.json" <<'PY'
import os, sys, json
rel = sys.argv[1]
betas = sorted(d for d in os.listdir(rel)
               if d.startswith("beta_") and os.path.isdir(os.path.join(rel, d)))
print(json.dumps([{"name": b, "type": "dir"} for b in betas], indent=2))
PY
echo "listing: $(python3 -c 'import json,sys;print(", ".join(x["name"] for x in json.load(open(sys.argv[1]))))' "$REL/index.json")"

# 3b. Web-flasher metadata (version.json + esp-web-tools manifests) — must roll
#     with the release so the flasher shows the current version + notes, not a
#     frozen one. Notes come from release-notes/<tag>.txt (one per line; optional).
python3 "$ROOT/scripts/build/gen-flasher-meta.py" "$TAG" "$LATEST" "$ROOT/release-notes/$TAG.txt"

# 3c. Mesh America Configurator provider catalog (apps.meshamerica.com — the web
#     flasher Cascadia Mesh uses). It is served LIVE from raw.githubusercontent
#     main, so each release must regenerate it for $TAG and push that ONE file to
#     main; otherwise the configurator keeps offering the previous beta. It points
#     at the immutable /releases/TOUCH/$TAG/ bins published below.
#     (Generator: deploy/gen-meshamerica-catalog.py — reads release-notes/$TAG.txt.)
CATALOG="$ROOT/deploy/meshamerica-catalog.json"
python3 "$ROOT/deploy/gen-meshamerica-catalog.py" "$TAG" > "$CATALOG.tmp" && mv "$CATALOG.tmp" "$CATALOG"
mkdir -p "$OUT/meshamerica" && cp "$CATALOG" "$OUT/meshamerica/catalog.json"   # also mirror to the VPS (enables the branded URL once its nginx location is deployed)
if git -C "$ROOT" diff --quiet -- "$CATALOG"; then
  echo "Mesh America catalog already current for $TAG"
elif [ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "main" ]; then
  if git -C "$ROOT" commit -q -m "chore: refresh Mesh America catalog for $TAG" -- "$CATALOG" \
       && git -C "$ROOT" push origin HEAD:main; then
    echo "Mesh America catalog refreshed + pushed to main ($TAG)"
  else
    echo "WARN: Mesh America catalog commit/push failed — push deploy/meshamerica-catalog.json to main by hand"
  fi
else
  echo "NOTE: regenerated $CATALOG for $TAG but not on 'main' — commit + push it to main so apps.meshamerica.com updates."
fi

# 4. Publish to the VPS (Cloudflare caches at the edge).
if [ -n "$DEST" ]; then
  rsync -av "$OUT/" "$DEST:$DEST_PATH/"
  echo "published $TAG -> $DEST:$DEST_PATH"
else
  echo "WADAMESH_VPS not set — built + staged in $REL/$TAG only (no publish)."
fi
