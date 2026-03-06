#!/bin/bash
# Wrapper: run sync and send summary to Discord (optional)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

DISCORD_WEBHOOK_HISTORY="${DISCORD_WEBHOOK_HISTORY:-${DISCORD_WEBHOOK_CRON:-${DISCORD_WEBHOOK_CRONY:-${DISCORD_WEBHOOK_URL:-}}}}"
DISCORD_NOTIFY_ON_SUCCESS="${DISCORD_NOTIFY_ON_SUCCESS:-1}"
DISCORD_NOTIFY_ON_FAILURE="${DISCORD_NOTIFY_ON_FAILURE:-1}"
NO_DISCORD="${NO_DISCORD:-0}"

TMP_OUTPUT="$(mktemp -t bybit-sync.XXXXXX)"
cleanup() { rm -f "$TMP_OUTPUT"; }
trap cleanup EXIT

json_escape() {
    local s="${1:-}"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    printf '%s' "$s"
}

send_discord() {
    local msg="${1:-}"
    [ -z "${DISCORD_WEBHOOK_HISTORY:-}" ] && return 0
    [ "${NO_DISCORD}" = "1" ] && return 0

    local payload
    if command -v jq &> /dev/null; then
        payload="$(jq -nc --arg content "$msg" '{content:$content}')"
    else
        payload="{\"content\":\"$(json_escape "$msg")\"}"
    fi

    curl -fsS -m 10 -X POST -H "Content-Type: application/json" \
        -d "$payload" "$DISCORD_WEBHOOK_HISTORY" >/dev/null 2>&1 || true
}

build_summary() {
    local lines
    lines="$(grep -E "DOWNLOAD SUMMARY|Total downloads:|Successful:|Failed:|Success rate:|Report saved:|ALL DOWNLOADS|Bybit sync:" "$TMP_OUTPUT" 2>/dev/null || true)"
    if [ -z "$lines" ]; then
        lines="$(tail -n 5 "$TMP_OUTPUT" 2>/dev/null || true)"
    fi
    if [ -n "$lines" ]; then
        echo "$lines" | head -n 12 | awk '{print substr($0,1,200)}'
    fi
}

set +e
bash "${SCRIPT_DIR}/run-sync.sh" 2>&1 | tee "$TMP_OUTPUT"
EXIT_CODE=${PIPESTATUS[0]}
set -e

SUMMARY="$(build_summary)"
if [ "$EXIT_CODE" -eq 0 ]; then
    if [ "${DISCORD_NOTIFY_ON_SUCCESS}" = "1" ]; then
        if [ -n "${SUMMARY:-}" ]; then
            send_discord "${SUMMARY}"
        else
            send_discord "Bybit sync completed"
        fi
    fi
else
    if [ "${DISCORD_NOTIFY_ON_FAILURE}" = "1" ]; then
        if [ -n "${SUMMARY:-}" ]; then
            send_discord "Bybit sync FAILED\n${SUMMARY}"
        else
            send_discord "Bybit sync FAILED"
        fi
    fi
fi

exit "$EXIT_CODE"
