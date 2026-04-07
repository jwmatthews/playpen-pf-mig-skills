#!/usr/bin/env bash
# claudeception.sh — Launch and interact with a nested Claude Code session via screen.
#
# Usage:
#   claudeception.sh launch [--dir=PATH]   Launch Claude Code in a detached screen session
#   claudeception.sh send MESSAGE           Send a prompt/message to Claude (+ Enter)
#   claudeception.sh approve                Press Enter to approve a permission prompt
#   claudeception.sh reject                 Press Escape to dismiss/reject a prompt
#   claudeception.sh keys ESCAPE_SEQ        Send raw escape sequences (e.g. arrow keys)
#   claudeception.sh capture                Show new output since last capture (clean)
#   claudeception.sh screen                 Show the full current screen (clean)
#   claudeception.sh wait_idle [OPTIONS]    Wait for output to stop changing
#     --idle-time=N   Seconds of silence before considered idle (default: 3)
#     --timeout=N     Max seconds to wait before giving up (default: 120)
#   claudeception.sh log                    Print the full raw terminal log
#   claudeception.sh status                 Show session status
#   claudeception.sh kill                   Kill the session and clean up
#   claudeception.sh clear                  Remove state files without killing
#
# capture uses screen's hardcopy for clean, readable output (no escape codes).
# wait_idle uses hardcopy snapshots to detect when the screen stops changing.
# log uses screen's raw logfile for complete history (includes escape codes).
#
# Escape sequences for 'keys' command (use $'...' quoting):
#   Arrow keys: $'\033[A' (Up) $'\033[B' (Down) $'\033[C' (Right) $'\033[D' (Left)
#   Enter: $'\r'   Escape: $'\033'   Tab: $'\t'
#   Ctrl-C: $'\x03'   Ctrl-D: $'\x04'   Ctrl-L: $'\x0c'
#
# Examples:
#   claudeception.sh launch --dir=/tmp/my-project
#   claudeception.sh send "/migration-comparison run evaluation mode"
#   claudeception.sh keys $'\033[B\033[B\r'   # Down Down Enter (navigate menu)
#   claudeception.sh approve                   # Accept a permission prompt
#   claudeception.sh capture                   # See what's new
#   claudeception.sh kill
# END_HELP

set -euo pipefail

SESSION_NAME="claudeception"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
LOG_FILE="/tmp/claudeception-screen.log"
SNAPSHOT_FILE="/tmp/claudeception-snapshot"
HARDCOPY_FILE="/tmp/claudeception-hardcopy"

session_exists() {
    screen -list 2>/dev/null | grep -q "\.${SESSION_NAME}[[:space:]]"
}

check_session() {
    if ! session_exists; then
        echo "Error: No active session. Run 'launch' first." >&2
        exit 1
    fi
}

cmd_launch() {
    local dir=""
    for arg in "$@"; do
        case "$arg" in
            --dir=*) dir="${arg#--dir=}" ;;
            *) echo "Unknown argument: $arg" >&2; exit 1 ;;
        esac
    done

    # Kill existing session if any
    if session_exists; then
        echo "Killing existing session..."
        screen -S "$SESSION_NAME" -X quit 2>/dev/null || true
        sleep 1
    fi
    rm -f "$LOG_FILE" "$SNAPSHOT_FILE" "$HARDCOPY_FILE"

    # Launch bash in a detached screen with scrollback history and logging
    screen -dmS "$SESSION_NAME" -h 50000 -L -Logfile "$LOG_FILE" bash
    sleep 1

    # Unset CLAUDECODE to allow nested session, cd to dir
    local setup_cmd="unset CLAUDECODE"
    if [[ -n "$dir" ]]; then
        setup_cmd="$setup_cmd && cd $dir"
    fi
    screen -S "$SESSION_NAME" -X stuff "${setup_cmd}"$'\r'
    sleep 1

    # Launch claude with TERM=dumb for cleaner output
    screen -S "$SESSION_NAME" -X stuff "TERM=dumb $CLAUDE_BIN"$'\r'
    sleep 5

    echo "Launched Claude in screen session: $SESSION_NAME"
    echo "Use 'capture' to see output, 'send' to interact."
}

cmd_send() {
    check_session
    local message="$*"

    if [[ -z "$message" ]]; then
        echo "Usage: claudeception.sh send MESSAGE" >&2
        exit 1
    fi

    # Send the message text without Enter, then send Enter separately
    screen -S "$SESSION_NAME" -X stuff "$message"
    sleep 0.5
    screen -S "$SESSION_NAME" -X stuff $'\r'
    echo "Sent: $message"
}

cmd_approve() {
    check_session
    screen -S "$SESSION_NAME" -X stuff $'\r'
    echo "Sent Enter (approve)."
}

cmd_reject() {
    check_session
    screen -S "$SESSION_NAME" -X stuff $'\033'
    echo "Sent Escape (reject)."
}

cmd_keys() {
    check_session

    if [[ $# -eq 0 ]]; then
        echo "Usage: claudeception.sh keys ESCAPE_SEQ" >&2
        echo "Example: claudeception.sh keys \$'\\033[B\\033[B\\r'  # Down Down Enter" >&2
        exit 1
    fi

    screen -S "$SESSION_NAME" -X stuff "$*"
    echo "Sent keys."
}

cmd_capture() {
    check_session

    # Take a clean screen snapshot (no escape codes, includes scrollback)
    screen -S "$SESSION_NAME" -X hardcopy -h "$HARDCOPY_FILE"
    sleep 0.2

    if [[ ! -f "$HARDCOPY_FILE" ]]; then
        echo "Error: Failed to capture output." >&2
        exit 1
    fi

    if [[ -f "$SNAPSHOT_FILE" ]]; then
        # Show only added lines using diff
        local changes
        changes=$(diff "$SNAPSHOT_FILE" "$HARDCOPY_FILE" 2>/dev/null | grep '^> ' | sed 's/^> //' || true)

        if [[ -n "$changes" ]]; then
            echo "$changes"
        else
            echo "(no new output)"
        fi
    else
        cat "$HARDCOPY_FILE"
    fi

    # Update snapshot for next diff
    cp "$HARDCOPY_FILE" "$SNAPSHOT_FILE"
}

cmd_screen() {
    check_session
    local tmp="/tmp/claudeception-screen-tmp"
    screen -S "$SESSION_NAME" -X hardcopy -h "$tmp"
    sleep 0.2
    if [[ -f "$tmp" ]]; then
        cat "$tmp"
        rm -f "$tmp"
    else
        echo "Error: Failed to capture screen." >&2
        exit 1
    fi
}

cmd_wait_idle() {
    check_session
    local idle_time=3
    local timeout=120

    for arg in "$@"; do
        case "$arg" in
            --idle-time=*) idle_time="${arg#--idle-time=}" ;;
            --timeout=*) timeout="${arg#--timeout=}" ;;
            *) echo "Unknown argument: $arg" >&2; exit 1 ;;
        esac
    done

    local wait_file="/tmp/claudeception-wait"
    local elapsed=0
    local silent=0

    # Take initial snapshot
    screen -S "$SESSION_NAME" -X hardcopy -h "$wait_file"
    sleep 0.2

    while [[ "$elapsed" -lt "$timeout" ]]; do
        sleep 1
        elapsed=$((elapsed + 1))

        local prev_hash curr_hash
        prev_hash=$(md5sum "$wait_file" 2>/dev/null | cut -d' ' -f1)

        screen -S "$SESSION_NAME" -X hardcopy -h "${wait_file}.new"
        sleep 0.1

        curr_hash=$(md5sum "${wait_file}.new" 2>/dev/null | cut -d' ' -f1)

        if [[ "$prev_hash" == "$curr_hash" ]]; then
            silent=$((silent + 1))
            if [[ "$silent" -ge "$idle_time" ]]; then
                rm -f "$wait_file" "${wait_file}.new"
                echo "Idle after ${elapsed}s (${idle_time}s of silence)."
                return 0
            fi
        else
            silent=0
            cp "${wait_file}.new" "$wait_file"
        fi
    done

    rm -f "$wait_file" "${wait_file}.new"
    echo "Timeout after ${timeout}s (not idle)." >&2
    return 1
}

cmd_log() {
    if [[ -f "$LOG_FILE" ]]; then
        cat "$LOG_FILE"
    else
        echo "No log file found." >&2
        exit 1
    fi
}

cmd_status() {
    if session_exists; then
        echo "Active session: $SESSION_NAME"
        screen -list 2>/dev/null | grep "$SESSION_NAME"
    else
        echo "No active session."
    fi
}

cmd_kill() {
    if session_exists; then
        screen -S "$SESSION_NAME" -X quit
        echo "Killed session: $SESSION_NAME"
    else
        echo "No active session."
    fi
    rm -f "$LOG_FILE" "$SNAPSHOT_FILE" "$HARDCOPY_FILE"
}

cmd_clear() {
    rm -f "$LOG_FILE" "$SNAPSHOT_FILE" "$HARDCOPY_FILE"
    echo "State files cleared."
}

cmd_help() {
    sed -n '2,/^# END_HELP/{ /^# END_HELP/d; s/^# \?//; p }' "$0"
}

# Main dispatch
case "${1:-help}" in
    launch)    shift; cmd_launch "$@" ;;
    send)      shift; cmd_send "$@" ;;
    approve)   cmd_approve ;;
    reject)    cmd_reject ;;
    keys)      shift; cmd_keys "$@" ;;
    capture)   cmd_capture ;;
    screen)    cmd_screen ;;
    wait_idle) shift; cmd_wait_idle "$@" ;;
    log)       cmd_log ;;
    status)    cmd_status ;;
    kill)      cmd_kill ;;
    clear)     cmd_clear ;;
    help|--help|-h) cmd_help ;;
    *) echo "Unknown command: $1. Run with 'help' for usage." >&2; exit 1 ;;
esac
