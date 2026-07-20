#!/bin/bash
# Regulatory Watch - Weekly Report
# Runs every Friday at 8:00 AM CET via launchd
# Launches Claude Code CLI with the full prompt

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROMPT_FILE="$HOME/.claude/regulatory-watch/prompt.md"
LOG_FILE="$HOME/.claude/regulatory-watch/last_run.log"

echo "=== Regulatory Watch Run: $(date) ===" > "$LOG_FILE"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOG_FILE"
    exit 1
fi

PROMPT=$(cat "$PROMPT_FILE")

# Run Claude Code in non-interactive mode with the full prompt
claude --print --dangerously-skip-permissions "$PROMPT" >> "$LOG_FILE" 2>&1

echo "=== Run completed: $(date) ===" >> "$LOG_FILE"
