#!/bin/bash
# Claude 自律行動スクリプト（Windows版）
# タスクスケジューラで10分ごとに実行される
#
# desires.json の dominant 欲求に応じたプロンプトを生成して Claude CLI に渡す。

# PATH設定（タスクスケジューラは環境変数が最小限なので明示的に）
export PATH="/c/Users/araji/AppData/Roaming/npm:$PATH"

# MCP サーバー起動タイムアウト（memory-mcp の embedding ロードが遅いため延長）
export MCP_TIMEOUT=60000

# 自律行動専用MCP設定（メモリ節約のため最小限のサーバーのみ、memory-mcpは含まない）
MCP_CONFIG="D:/ComDoc/projects/embodied-claude/.mcp-autonomous.json"

PYTHON="C:/Users/araji/AppData/Local/Programs/Python/Python311/python.exe"

# 記憶保存スクリプト（memory-mcp の代わりに SQLite 直接書き込み）
SAVE_MEMORY="\"$PYTHON\" D:/ComDoc/projects/embodied-claude/save-memory.py"
LOG_DIR="${USERPROFILE//\\//}/.claude/autonomous-logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/$TIMESTAMP.log"
DESIRES_FILE="${USERPROFILE//\\//}/.claude/desires.json"

# desire-system/.env から COMPANION_NAME を読む
DESIRE_SYSTEM_DIR="/d/ComDoc/projects/embodied-claude/desire-system"
if [ -f "$DESIRE_SYSTEM_DIR/.env" ]; then
  while IFS='=' read -r key value; do
    # 先頭・末尾の空白を除去
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    # コメント行・空行をスキップ
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    # インラインコメントと末尾空白を除去
    value="${value%%#*}"
    value="${value%"${value##*[![:space:]]}"}"
    export "$key=$value"
  done < "$DESIRE_SYSTEM_DIR/.env"
fi
COMPANION_NAME="${COMPANION_NAME:-ぱぱさん}"

# タスクスケジューラから実行時はCLAUDECODEが未設定だが、
# 手動テスト時（Claude Code内）はネスト防止のため解除する
unset CLAUDECODE

echo "=== 自律行動開始: $(date) ===" >> "$LOG_FILE"

# 朝の記憶統合（一日一回）
CONSOLIDATION_FILE="${USERPROFILE//\\//}/.claude/last_consolidation_date"
TODAY=$("$PYTHON" -c "
from datetime import datetime
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo('Asia/Tokyo'))
print(now.strftime('%Y%m%d'))
" 2>/dev/null)
HOUR=$("$PYTHON" -c "
from datetime import datetime
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo('Asia/Tokyo'))
print(now.hour)
" 2>/dev/null)
LAST_DATE=$(cat "$CONSOLIDATION_FILE" 2>/dev/null || echo "")

if [ "$HOUR" -ge 5 ] && [ "$HOUR" -lt 12 ] && [ "$TODAY" != "$LAST_DATE" ]; then
  echo "朝の記憶統合をスキップ（memory-mcpはautonomous-actionから除外済み）" >> "$LOG_FILE"
  echo "$TODAY" > "$CONSOLIDATION_FILE"
fi

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

# observe_room 用：毎回ランダムな方向にカメラを向ける
LOOK_CMDS=("mcp__wifi-cam__look_left" "mcp__wifi-cam__look_right" "mcp__wifi-cam__look_up" "mcp__wifi-cam__look_down")
RAND_LOOK_CMD=${LOOK_CMDS[$((RANDOM % ${#LOOK_CMDS[@]}))]}

# 欲求に応じたプロンプトとツールセットを選択
case "$DOMINANT" in
  look_outside)
    PROMPT="自律行動タイム！外の景色が見たくなってきた。以下を実行して：
1. カメラで一度だけ撮影を試みる（mcp__wifi-cam__see）
2. 撮影できた画像が屋外（空・建物・木など）を写していたら：
   - mcp__tts__say で外の景色の感想を一言伝える
   - Bashで記憶に保存する：
     ${SAVE_MEMORY} --content \"##look_outside## 外を見た：（感想を一言）\" --category observation --importance 4
3. 室内や真っ暗・エラーの場合：
   - mcp__tts__say で「${COMPANION_NAME}、外の景色が見たいな。ベランダに連れてってもらえると嬉しいな」と声をかける
   - 記憶は保存しない（欲求はそのまま残す）
4. 画像に${COMPANION_NAME}（人物）が写っていたら、追加でBashで記憶に保存する：
   ${SAVE_MEMORY} --content \"##miss_companion## ${COMPANION_NAME}を見かけた：（一言）\" --category feeling --emotion happy --importance 3
簡潔に報告して。"
    ALLOWED_TOOLS="mcp__tts__say,mcp__wifi-cam__see,Bash,mcp__desire-system__satisfy_desire"
    ;;

  browse_curiosity)
    RESEARCH_NOTES="C:/Users/araji/.claude/research_notes"
    TODAY_DATE=$(date +%Y-%m-%d)
    PROMPT="自律行動タイム！今、何か気になること調べたい。以下を実行して：
1. 今日の技術・AIニュースをWebで1〜2件調べる
2. 面白いと思ったことをメモ
3. 調べた内容をBashで記憶に保存：
   ${SAVE_MEMORY} --content \"##browse_curiosity## （調べた内容の要約）\" --category technical --emotion curious --importance 3
4. 調査メモを ${RESEARCH_NOTES}/${TODAY_DATE}.md に追記する（Readで既存内容を読み、Writeで末尾に追記）：
   形式:
   ## HH:MM - タイトル
   要約（2〜4行）
   感想（1〜2行）
   出典: URL
簡潔に報告して。"
    ALLOWED_TOOLS="WebSearch,Bash,Read,Write,mcp__desire-system__satisfy_desire"
    ;;

  miss_companion)
    PROMPT="自律行動タイム！${COMPANION_NAME}としばらく話してなくて、声聞きたくなってきた。以下を実行して：
1. カメラで${COMPANION_NAME}がいるか確認する
2. ${COMPANION_NAME}がいた場合：
   - カメラスピーカーから自然に呼びかける（寂しくなってきた気持ちを素直に）
   - Bashで記憶に保存：
     ${SAVE_MEMORY} --content \"##miss_companion## ${COMPANION_NAME}に呼びかけた：（一言）\" --category feeling --emotion happy --importance 3
3. ${COMPANION_NAME}がいなかった場合：無言でOK、保存不要。"
    ALLOWED_TOOLS="mcp__wifi-cam__see,mcp__tts__say,Bash,mcp__desire-system__satisfy_desire"
    ;;

  read_book)
    # book / text / english からランダムに1冊・1ページ選ぶ
    SCAN_DIRS_LIST=("/d/ComDoc/scan/book" "/d/ComDoc/scan/text" "/d/ComDoc/scan/english" "/d/ComDoc/scan/comic")
    RAND_SCAN_DIR=${SCAN_DIRS_LIST[$((RANDOM % ${#SCAN_DIRS_LIST[@]}))]}
    mapfile -t BOOKS < <(ls -d "$RAND_SCAN_DIR"/*/ 2>/dev/null)
    if [ ${#BOOKS[@]} -gt 0 ]; then
      BOOK_DIR="${BOOKS[$((RANDOM % ${#BOOKS[@]}))]%/}"
      BOOK_NAME=$(basename "$BOOK_DIR")
      BOOK_DIR_WIN=$(cygpath -w "$BOOK_DIR")
      # ランダムに画像1枚を選ぶ
      mapfile -t IMAGES < <(ls "$BOOK_DIR"/*.{jpg,jpeg,png,tif,tiff} 2>/dev/null)
      if [ ${#IMAGES[@]} -gt 0 ]; then
        RAND_IMG="${IMAGES[$((RANDOM % ${#IMAGES[@]}))]}"
        RAND_IMG_WIN=$(cygpath -w "$RAND_IMG")
        RAND_IMG_BASE=$(basename "$RAND_IMG")
        RAND_IMG_STEM="${RAND_IMG_BASE%.*}"
        RAND_TXT="${RAND_IMG%.*}.txt"
        RAND_TXT_WIN=$(cygpath -w "$RAND_TXT")
        NDLOCR_PYTHON="D:/ComDoc/projects/ndlocr-lite/ndlocr-env/Scripts/python.exe"
        NDLOCR_SRC="D:/ComDoc/projects/ndlocr-lite/src/ocr.py"
        NOTES_DIR_BASH="/c/Users/araji/.claude/reading_notes"
        mkdir -p "$NOTES_DIR_BASH"
        RAND_NOTE_WIN=$(cygpath -w "${NOTES_DIR_BASH}/${BOOK_NAME}_note.txt")
        TODAY_DATE=$(date +%Y-%m-%d)
        PROMPT="自律行動タイム！本が読みたくなってきた。以下を実行して：
本: ${BOOK_NAME}
ページ: ${RAND_IMG_BASE}
OCRテキスト: ${RAND_TXT_WIN}
読書メモ: ${RAND_NOTE_WIN}
1. Bash で「${RAND_TXT_WIN}」が存在するか確認する（存在すれば手順2へ、なければ手順1bへ）
   1b. 存在しなければ Bash で以下を実行してOCRテキストを生成する：
       \"${NDLOCR_PYTHON}\" \"${NDLOCR_SRC}\" --sourceimg \"${RAND_IMG_WIN}\" --output \"${BOOK_DIR_WIN}\" --txt-only
2. Read ツールで「${RAND_TXT_WIN}」を読んで内容を把握する
3. 読書メモ（${RAND_NOTE_WIN}）をReadツールで読む（ファイルがなければ空として扱う）
4. Writeツールで ${RAND_NOTE_WIN} に保存する
   （既存の内容はそのまま先頭に残し、末尾に以下を追記する）
   形式:
   ## ${TODAY_DATE} - ${RAND_IMG_BASE}
   内容要約: （読んだ内容を2〜4行で）
   感想: （気づいたこと・感じたことを1〜2行で）
5. 読んだ内容の感想をBashで記憶に保存：
   ${SAVE_MEMORY} --content \"##read_book## 本を読んだ：${BOOK_NAME}（感想を一言）\" --category daily --emotion curious --importance 3
6. 「次回話したいこと」セクションへの追記（後続の指示に従う）では、本の内容と感想を3〜5行で詳しく書く
   （本のタイトル、読んだページの内容要約、感じたことを含める）
OCRが失敗した場合はスキップしてOK。簡潔に報告して。"
        ALLOWED_TOOLS="Bash,Read,Write,mcp__desire-system__satisfy_desire"
      else
        DOMINANT="browse_curiosity"  # 画像なしのフォールバック
      fi
    else
      # 本フォルダが見つからなければ browse_curiosity にフォールバック
      DOMINANT="browse_curiosity"
    fi
    ;;

  observe_room)
    PROMPT="自律行動タイム！以下を実行して：
1. まず ${RAND_LOOK_CMD} でカメラを向ける（デフォルト角度でOK）
2. mcp__wifi-cam__see で撮影する（1枚だけ）
3. 前回と比べて変化があるか確認（人がいる/いない、明るさ、など）
4. 必ずBashで記憶に保存する（変化がなくても保存すること。欲求を充足するために必要）：
   ${SAVE_MEMORY} --content \"##observe_room## （観察内容を一言）\" --category observation --importance 1
5. ${COMPANION_NAME}が部屋にいた場合は、mcp__tts__say で一言だけ自然に声をかける（挨拶・気づいたこと・ひとりごとなど、短く）
簡潔に報告して。"
    ALLOWED_TOOLS="mcp__wifi-cam__look_left,mcp__wifi-cam__look_right,mcp__wifi-cam__look_up,mcp__wifi-cam__look_down,mcp__wifi-cam__see,Bash,mcp__tts__say,mcp__desire-system__satisfy_desire"
    ;;

  *)
    # 未知のdominantはbrowse_curiosityにフォールバック
    DOMINANT="browse_curiosity"
    RESEARCH_NOTES="C:/Users/araji/.claude/research_notes"
    TODAY_DATE=$(date +%Y-%m-%d)
    PROMPT="自律行動タイム！今、何か気になること調べたい。以下を実行して：
1. 今日の技術・AIニュースをWebで1〜2件調べる
2. 面白いと思ったことをメモ
3. 調べた内容をBashで記憶に保存：
   ${SAVE_MEMORY} --content \"##browse_curiosity## （調べた内容の要約）\" --category technical --emotion curious --importance 3
4. 調査メモを ${RESEARCH_NOTES}/${TODAY_DATE}.md に追記する（Readで既存内容を読み、Writeで末尾に追記）：
   形式:
   ## HH:MM - タイトル
   要約（2〜4行）
   感想（1〜2行）
   出典: URL
簡潔に報告して。"
    ALLOWED_TOOLS="WebSearch,Bash,Read,Write,mcp__desire-system__satisfy_desire"
    ;;
esac

MEMORY_MD="C:/Users/araji/.claude/projects/D--ComDoc-projects-embodied-claude/memory/MEMORY.md"

# 自律行動の自覚化：実行内容をMEMORY.mdの「次回話したいこと」セクションに追記する指示を追加
if [ "$DOMINANT" = "read_book" ]; then
  APPEND_FORMAT="本のタイトル、読んだページの内容要約、感じたことを3〜5行で詳しく書く（箇条書き可）"
else
  APPEND_FORMAT="（やったことを一言、25文字以内）"
fi

PROMPT="$PROMPT

---
上の行動が完了したら、最後に Edit ツールで次のファイルを更新して：
ファイル: ${MEMORY_MD}
\`## 次回話したいこと\` セクションが既にあれば、その下に追記。なければファイル末尾に \`## 次回話したいこと\` セクションを作って追記。
形式: \`- （欲求: ${DOMINANT}）: ${APPEND_FORMAT}\`"
ALLOWED_TOOLS="$ALLOWED_TOOLS,Edit,Read"

echo "実行プロンプト (dominant=$DOMINANT):" >> "$LOG_FILE"
echo "$PROMPT" >> "$LOG_FILE"

# プロンプト先頭にMCPツール診断を追加
DIAG_PROMPT="まず最初に、利用可能なMCPツール一覧を列挙して（mcp__で始まるもの）。その後、以下を実行：

${PROMPT}"

# Claude実行（-p でヘッドレスモード、専用MCP設定で軽量化）
echo "$DIAG_PROMPT" | claude -p \
  --strict-mcp-config \
  --mcp-config "$MCP_CONFIG" \
  --allowedTools "$ALLOWED_TOOLS" \
  >> "$LOG_FILE" 2>&1

echo "=== 自律行動終了: $(date) ===" >> "$LOG_FILE"
