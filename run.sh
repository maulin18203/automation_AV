#!/bin/bash
# ─── BRIGHTHAVEN CLOUD IOT ────────────────────────────────────────────────────
# Professional Launcher v4.0 — THE DEFINITIVE EDITION
# Optimized for high-performance deployment and stability
# ──────────────────────────────────────────────────────────────────────────────

# 1. DIRECTORY & LOG SETUP
WORKSPACE_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_DIR="$(dirname "$WORKSPACE_DIR")"
LOG_FILE="$PARENT_DIR/flask_error.log"

# Fibonacci & Premium Colors
GOLD='\033[1;33m'
TEAL='\033[1;36m'
RED='\033[1;31m'
GREEN='\033[1;32m'
PURPLE='\033[1;35m'
NC='\033[0m'

clear
echo -e "${PURPLE}╔═════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║${NC}  ${TEAL}____       _       _     _   _    _                        ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC} ${TEAL}|  _ \     (_)     | |   | | | |  | |                       ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC} ${TEAL}| |_) |_ __ _  __ _| |__ | |_| |__| | __ ___   _____ _ __   ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC} ${TEAL}|  _ <| '__| |/ _\` | '_ \| __|  __  |/ _\` \ \ / / _ \ '_\\   ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC} ${TEAL}| |_) | |  | | (_| | | | | |_| |  | | (_| |\ V /  __/ | | |    ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC} ${TEAL}|____/|_|  |_|\__, |_| |_|\__|_|  |_|\__,_| \_/ \___|_| |_|    ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC}  ${TEAL}              __/ |                                         ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC}  ${TEAL}             |___/           ULTRA PRO MAX EDITION          ${PURPLE}║${NC}"
echo -e "${PURPLE}╚═══════════════════════════════════════════════════════════════╝${NC}"

# 2. INSTANCE LOCK
PID_FILE="$WORKSPACE_DIR/.brighthaven.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null; then
        echo -e "${RED}⚠ BrightHaven is already running (PID: $OLD_PID)${NC}"
        echo -e "${GOLD}Kill existing process? (y/n)${NC}"
        read -r -t 5 confirm
        if [[ "$confirm" == "y" ]]; then
            kill -9 "$OLD_PID" && rm "$PID_FILE"
            echo -e "${GREEN}✓ Previous instance terminated.${NC}"
        else
            echo "Exiting."
            exit 1
        fi
    else
        rm "$PID_FILE"
    fi
fi

# 3. ENVIRONMENT & VIRTUAL ENV
echo -e "${GOLD}» Initializing Environment...${NC}"
if [ -d "$PARENT_DIR/.venv" ]; then
    source "$PARENT_DIR/.venv/bin/activate"
    echo -e "  ${GREEN}✓ Virtual Env [Parent] Active${NC}"
elif [ -d "$WORKSPACE_DIR/.venv" ]; then
    source "$WORKSPACE_DIR/.venv/bin/activate"
    echo -e "  ${GREEN}✓ Virtual Env [Local] Active${NC}"
fi

# Load .env
if [ -f "$PARENT_DIR/.env" ]; then
    set -a; source "$PARENT_DIR/.env"; set +a
    echo -e "  ${GREEN}✓ Config loaded from Parent .env${NC}"
elif [ -f "$WORKSPACE_DIR/.env" ]; then
    set -a; source "$WORKSPACE_DIR/.env"; set +a
    echo -e "  ${GREEN}✓ Config loaded from Local .env${NC}"
fi

# 4. DEPENDENCY CHECK
if [ -f "requirements.txt" ]; then
    echo -e "${GOLD}» Checking Dependencies...${NC}"
    pip install -r requirements.txt --break-system-packages -q > /dev/null 2>&1
    echo -e "  ${GREEN}✓ Core Libraries Verified${NC}"
fi

# 5. SMART PORT RESOLUTION
PORT=${FLASK_PORT:-5000}
while lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; do
    echo -e "  ${GOLD}⚠ Port $PORT busy, incrementing...${NC}"
    PORT=$((PORT + 1))
done
export FLASK_PORT=$PORT

# 6. DATABASE & LOGS
echo -e "${GOLD}» Preparing System Logs...${NC}"
[ -f "$LOG_FILE" ] && cp "$LOG_FILE" "$LOG_FILE.bak"
echo -e "--- Session Start: $(date) ---" > "$LOG_FILE"

# 7. NETWORK DISCOVERY
IP_ADDR=$(hostname -I | awk '{print $1}')
echo -e "\n${TEAL}╔════════════════ NETWORK CONNECTIVITY ════════════════════╗${NC}"
echo -e "${TEAL}║${NC}  Local:   ${GREEN}http://127.0.0.1:$PORT${NC}   ${TEAL}║${NC}"
[ -n "$IP_ADDR" ] && echo -e "${TEAL}║${NC}  Network: ${GREEN}http://$IP_ADDR:$PORT${NC}${TEAL}║${NC}"
echo -e "${TEAL}╚══════════════════════════════════════════════════════════╝${NC}"

# 8. LAUNCH BROWSER
(sleep 3 && xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 &)

# 9. EXECUTION ENGINE
echo -e "${PURPLE}» DEPLOYING BRIGHTHAVEN ENGINE...${NC}\n"

# Store PID
echo $$ > "$PID_FILE"

if command -v gunicorn >/dev/null 2>&1; then
    # Production Optimized
    exec gunicorn run:app \
        --bind 0.0.0.0:$PORT \
        --workers 4 \
        --threads 4 \
        --worker-class gthread \
        --timeout 120 \
        --keep-alive 5 \
        --access-logfile - \
        --error-logfile "$LOG_FILE" \
        --preload \
        --capture-output \
        --log-level info
else
    # Development Fallback
    echo -e "${RED}⚠ Gunicorn not found. Falling back to Flask Dev Server.${NC}"
    export FLASK_DEBUG=1
    python3 run.py
fi