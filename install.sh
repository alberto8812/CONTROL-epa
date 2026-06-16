#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "  NovaHold — Instalador"
echo ""

# 1. Check Python 3.11+
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗  Python 3 no encontrado.${NC}"
    echo "   Descargá desde https://python.org"
    exit 1
fi

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    echo -e "${RED}✗  Requiere Python 3.11+ (encontrado: $PY_VER)${NC}"
    echo "   Descargá desde https://python.org"
    exit 1
fi
echo -e "${GREEN}✓  Python $PY_VER${NC}"

# 2. Check/install pipx
if ! command -v pipx &>/dev/null; then
    echo -e "${YELLOW}  Instalando pipx...${NC}"
    python3 -m pip install --user pipx --quiet
    python3 -m pipx ensurepath
    export PATH="$HOME/.local/bin:$PATH"
fi
echo -e "${GREEN}✓  pipx listo${NC}"

# 3. Install novahold
echo "  Instalando novahold..."
pipx install "$SCRIPT_DIR" --force --quiet
echo -e "${GREEN}✓  novahold instalado${NC}"

# 4. Install Chromium (Playwright browser)
echo "  Instalando Chromium (puede tardar unos minutos)..."
PIPX_HOME="${PIPX_HOME:-$HOME/.local/pipx}"
PLAYWRIGHT_BIN="$PIPX_HOME/venvs/novahold/bin/playwright"
if [ -f "$PLAYWRIGHT_BIN" ]; then
    "$PLAYWRIGHT_BIN" install chromium
    echo -e "${GREEN}✓  Chromium listo${NC}"
else
    echo -e "${YELLOW}⚠  No se encontró playwright en el venv.${NC}"
    echo "   Ejecutá manualmente: playwright install chromium"
fi

echo ""
echo -e "${GREEN}  ¡Instalación completa!${NC}"
echo ""
echo "  Si 'nova' no aparece como comando, ejecutá:"
echo "    source ~/.zshrc   (macOS)"
echo "    source ~/.bashrc  (Linux)"
echo ""
echo "  Luego ejecutá: nova"
echo ""
