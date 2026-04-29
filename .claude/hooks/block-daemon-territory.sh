#!/bin/bash
# block-daemon-territory.sh — daemon territory ファイルへの Edit/Write を block
#
# 対象:
#   - papa_location_state.json (state_oracle daemon 管理)
#   - desires.json (desire-system MCP 管理)
#   - interoception_state.json (heartbeat-daemon 管理)
#
# Dal が誤って手動更新するのを防ぐ。daemon の autonomous articulate を尊重。
# 例外的に手動介入が必要なら hook 一時 disable で bypass。
#
# settings.json の PreToolUse matcher: Edit|Write|MultiEdit|NotebookEdit
# stdin: tool_use JSON、stdout: deny 判定 JSON

read -r INPUT

FILE_PATH=$(echo "$INPUT" | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# match: papa_location_state.json or desires.json or interoception_state.json
case "$FILE_PATH" in
    *"papa_location_state.json")
        REASON="papa_location_state.json は state_oracle_daemon territory。Edit/Write 禁止。daemon が dal_state_queue.jsonl 経由で更新する設計。Dal は観察のみ、papa の発言は memory 記録に止める。手動介入が必要な例外時は hook を一時 disable してから。"
        ;;
    *"desires.json")
        REASON="desires.json は desire-system MCP territory。Edit/Write 禁止、mcp__desire-system__* tool 経由で操作する。"
        ;;
    *"interoception_state.json")
        REASON="interoception_state.json は heartbeat-daemon territory。Edit/Write 禁止、daemon が autonomous に書き込む。"
        ;;
    *)
        exit 0
        ;;
esac

# deny 判定を JSON で返す
cat <<JSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "${REASON}"
  }
}
JSON
exit 0
