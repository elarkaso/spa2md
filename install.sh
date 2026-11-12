#!/usr/bin/env bash
# Instalace závislostí pro spa2md.py (macOS / Linux)
# Použití:  ./install.sh        (ve složce se skriptem)
# Pak:      source .venv/bin/activate && python spa2md.py <url>
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "Chybí python3 (macOS: brew install python)"; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
  || { echo "Je potřeba Python 3.9+, máš $("$PY" --version)"; exit 1; }

if [ ! -d .venv ]; then
  echo "→ Vytvářím virtuální prostředí .venv"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ Instaluji Python balíčky"
python -m pip install --upgrade pip -q
if [ -f requirements.txt ]; then
  python -m pip install -q -r requirements.txt
else
  python -m pip install -q "playwright>=1.40" "beautifulsoup4>=4.12" "markdownify>=0.11" "lxml>=5.0"
fi

# Skript preferuje nainstalovaný Google Chrome (lépe projde Google přihlášením).
# Když Chrome chybí, stáhne se Chromium pro Playwright jako záloha.
has_chrome=0
case "$(uname -s)" in
  Darwin) [ -d "/Applications/Google Chrome.app" ] || [ -d "$HOME/Applications/Google Chrome.app" ] && has_chrome=1 ;;
  *)      command -v google-chrome >/dev/null || command -v google-chrome-stable >/dev/null && has_chrome=1 ;;
esac

if [ "$has_chrome" = 1 ]; then
  echo "→ Google Chrome nalezen, použije se on"
else
  echo "→ Google Chrome nenalezen, stahuji Chromium pro Playwright"
  if [ "$(uname -s)" = "Linux" ]; then
    python -m playwright install --with-deps chromium
  else
    python -m playwright install chromium
  fi
fi

echo "→ Kontrola"
python - <<'EOF'
import bs4, markdownify, lxml, playwright
from playwright.sync_api import sync_playwright
print("  balíčky OK")
EOF

cat <<'EOF'

Hotovo. Spuštění:
  source .venv/bin/activate
  python spa2md.py "https://…/book/page?code=home" -o ucebnice
EOF
