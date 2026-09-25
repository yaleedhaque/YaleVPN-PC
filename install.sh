#!/usr/bin/env bash
# YaleVPN-PC installer — Linux
# Copies the client into ~/.local (no root needed) and prints next steps.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO/src/yalevpn"
LIBDIR="${XDG_DATA_HOME:-$HOME/.local/share}/yalevpn"
BINDIR="${YALEVPN_BIN:-$HOME/.local/bin}"
PY="${PYTHON:-$(command -v python3 || true)}"

if [ -z "$PY" ]; then
  echo "error: python3 not found (apt install python3)" >&2
  exit 1
fi

mkdir -p "$LIBDIR" "$BINDIR"
rm -rf "$LIBDIR/src"
mkdir -p "$LIBDIR/src"
cp -r "$SRC" "$LIBDIR/src/yalevpn"

cat > "$BINDIR/yalevpn" <<EOF
#!/usr/bin/env bash
# YaleVPN-PC launcher (installed by install.sh)
export PYTHONPATH="$LIBDIR/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PY" -m yalevpn "\$@"
EOF
chmod +x "$BINDIR/yalevpn"
ln -sf "$BINDIR/yalevpn" "$BINDIR/yalevpn-pc"

# optional: systemd units for auto-start + periodic WARP rotation
UNIT_DIR="$HOME/.config/systemd/user"
if [ -d "$UNIT_DIR" ] || mkdir -p "$UNIT_DIR" 2>/dev/null; then
  cp "$REPO/systemd/yalevpn-autostart.service" "$UNIT_DIR/" 2>/dev/null || true
  cp "$REPO/systemd/yalevpn-rotate.service"    "$UNIT_DIR/" 2>/dev/null || true
  cp "$REPO/systemd/yalevpn-rotate.timer"      "$UNIT_DIR/" 2>/dev/null || true
fi

echo "installed: $BINDIR/yalevpn  (python: $PY)"
echo
echo "then run:"
echo "  yalevpn doctor        # see what backends are available"
echo "  yalevpn add server.conf   # import a WireGuard profile"
echo "  yalevpn up warp       # or a profile name"
echo "  yalevpn gui           # desktop control panel"
echo
if [ ! -f "$LIBDIR/.crypto" ] && "$PY" -c "import cryptography" 2>/dev/null; then
  touch "$LIBDIR/.crypto"
fi