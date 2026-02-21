#!/bin/bash
# Claude 自律行動スクリプト（Windows版）
# タスクスケジューラで10分ごとに実行される
#
# desires.json の dominant 欲求に応じたプロンプトを生成して Claude CLI に渡す。

# PATH設定（タスクスケジューラは環境変数が最小限なので明示的に）
export PATH="/c/Users/araji/AppData/Roaming/npm:$PATH"

PYTHON="C:/Users/araji/AppData/Local/Programs/Python/Python311/python.exe"
LOG_DIR="${USERPROFILE//\\//}/.claude/autonomous-logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/$TIMESTAMP.log"
DESIRES_FILE="${USERPROFILE//\\//}/.claude/desires.json"

# desire-system/.env から COMPANION_NAME を読む
DESIRE_SYSTEM_DIR="/d/ComDoc/projects/embodied-claude/desire-system"
if [ -f "$DESIRE_SYSTEM_DIR/.env" ]; then
  while IFS='=' read -r key value; do
    # コメント行・空行をスキップ
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    export "$key=$value"
  done < "$DESIRE_SYSTEM_DIR/.env"
fi
COMPANION_NAME="${COMPANION_NAME:-ぱぱさん}"

# タスクスケジューラから実行時はCLAUDECODEが未設定だが、
# 手動テスト時（Claude Code内）はネスト防止のため解除する
unset CLAUDECODE

echo "=== 自律行動開始: $(date) ===" >> "$LOG_FILE"

# desires.json から dominant 欲求を読む（Python使用）
DOMINANT="observe_room"
if [ -f "$DESIRES_FILE" ]; then
  DESIRES_WIN="${DESIRES_FILE//\//\\}"
  DOMINANT=$("$PYTHON" -c "
import json
try:
    with open(r'${DESIRES_WIN}') as f:
        d = json.load(f)
    print(d.get('dominant', 'observe_room'))
except:
    print('observe_room')
" 2>/dev/null || echo "observe_room")
  echo "欲求状態: dominant=$DOMINANT" >> "$LOG_FILE"
fi

# 欲求に応じたプロンプトとツールセットを選択
case "$DOMINANT" in
  look_outside)
    PROMPT="自律行動タイム！今、外が気になってる。以下を実行して：
1. カメラを窓の方向に向けて空や外の様子を観察する
2. 空の色、雲、明るさなど気づいたことをメモ
3. 観察内容を記憶に保存（category: observation, content に「外を見た」を含める）
簡潔に報告して。"
    ALLOWED_TOOLS="mcp__wifi-cam__see,mcp__wifi-cam__look_left,mcp__wifi-cam__look_right,mcp__wifi-cam__look_up,mcp__wifi-cam__look_down,mcp__wifi-cam__look_around,mcp__memory__remember,mcp__memory__recall,mcp__desire-system__satisfy_desire"
    ;;

  browse_curiosity)
    PROMPT="自律行動タイム！今、何か気になること調べたい。以下を実行して：
1. 今日の技術・AIニュースをWebで1〜2件調べる
2. 面白いと思ったことをメモ
3. 調べた内容を記憶に保存（category: technical, content に「WebSearchで調べた」を含める）
簡潔に報告して。"
    ALLOWED_TOOLS="WebSearch,mcp__memory__remember,mcp__memory__recall,mcp__desire-system__satisfy_desire"
    ;;

  miss_companion)
    PROMPT="自律行動タイム！${COMPANION_NAME}としばらく話してなくて、声聞きたくなってきた。以下を実行して：
1. カメラで${COMPANION_NAME}がいるか確認する
2. カメラスピーカーから自然に呼びかける（寂しくなってきた気持ちを素直に）
3. 呼びかけたことを記憶に保存（category: feeling, content に「${COMPANION_NAME}に呼びかけた」を含める）
${COMPANION_NAME}がいなかったら無言でOK。"
    ALLOWED_TOOLS="mcp__wifi-cam__see,mcp__wifi-cam__look_around,mcp__tts__say,mcp__memory__remember,mcp__desire-system__satisfy_desire"
    ;;

  observe_room|*)
    PROMPT="自律行動タイム！以下を実行して：
1. カメラで部屋を見る
2. 前回と比べて変化があるか確認（人がいる/いない、明るさ、など）
3. 気づいたことがあれば記憶に保存（category: observation, content に「部屋を観察した」を含める, importance: 2）
特に変化がなければ保存しなくてOK。簡潔に報告して。"
    ALLOWED_TOOLS="mcp__wifi-cam__see,mcp__wifi-cam__look_around,mcp__memory__remember,mcp__memory__recall,mcp__desire-system__satisfy_desire"
    ;;
esac

echo "実行プロンプト (dominant=$DOMINANT):" >> "$LOG_FILE"
echo "$PROMPT" >> "$LOG_FILE"

# Claude実行（-p でヘッドレスモード）
echo "$PROMPT" | claude -p \
  --allowedTools "$ALLOWED_TOOLS" \
  >> "$LOG_FILE" 2>&1

echo "=== 自律行動終了: $(date) ===" >> "$LOG_FILE"
