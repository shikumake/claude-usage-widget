#!/bin/bash
# Claude 使用量 & Claude Code 稼働状況ウィジェット（非公式） インストーラ
#
# 使い方（どちらでも可）:
#   curl -fsSL https://raw.githubusercontent.com/shikumake/claude-usage-widget/main/install.sh | bash
#   bash install.sh        （リポジトリをダウンロードした場合）
#
# 何度実行しても大丈夫です（上書き更新されます）。
set -e
REPO="shikumake/claude-usage-widget"
BRANCH="main"
DEST="$HOME/.claude-widget"
PY="$(command -v python3 || true)"
SETTINGS="$HOME/.claude/settings.json"
PLIST="$HOME/Library/LaunchAgents/com.claudewidget.poll.plist"
SCRIPTABLE="$HOME/Library/Mobile Documents/iCloud~dk~simonbs~Scriptable/Documents"
KEYCHAIN_SERVICE="Claude Code-credentials"

ok()   { printf "\033[32m✔\033[0m %s\n" "$1"; }
warn() { printf "\033[33m!\033[0m %s\n" "$1"; }

# 対話できるとき（ターミナルで実行したとき）だけ質問する。
# curl | bash で実行すると標準入力はスクリプト本体なので、/dev/tty から読む。
ask_yes() {
  local ans
  if { exec 3</dev/tty; } 2>/dev/null; then
    read -r -p "$1 [Y/n] " ans <&3 || ans="n"
    exec 3<&-
    case "$ans" in [nN]*) return 1 ;; *) return 0 ;; esac
  fi
  return 1
}

echo "=== Claude 使用量ウィジェット（非公式） インストール ==="

if [ "$(uname)" != "Darwin" ]; then
  warn "このツールは macOS 専用です。"
  exit 1
fi

# 1) Python
if [ -z "$PY" ] || ! "$PY" -c 'import sys; assert sys.version_info >= (3,8)' 2>/dev/null; then
  warn "python3 が使えません。表示されたダイアログでコマンドライン・デベロッパツールを入れてから、もう一度実行してください。"
  xcode-select --install 2>/dev/null || true
  exit 1
fi
ok "python3: $PY"

# 2) ファイルの場所（curl | bash のときは GitHub から取得）
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/claude_widget.py" ]; then
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" | tar -xz -C "$TMP" --strip-components 1
  SRC="$TMP"
  ok "GitHub から最新版を取得"
fi

# 3) スクリプトを配置
mkdir -p "$DEST"
cp "$SRC/claude_widget.py" "$DEST/claude_widget.py"
chmod +x "$DEST/claude_widget.py"
ok "スクリプトを $DEST に配置"

# 4) Claude Code の設定（ステータスライン＋フック）
mkdir -p "$HOME/.claude"
[ -f "$SETTINGS" ] && cp "$SETTINGS" "$SETTINGS.bak-claude-widget-$(date +%Y%m%d%H%M%S)"
"$PY" - "$SETTINGS" "$PY" "$DEST" <<'PYEOF'
import json, os, sys
path, py, dest = sys.argv[1], sys.argv[2], sys.argv[3]
script = os.path.join(dest, "claude_widget.py")
try:
    s = json.load(open(path))
except FileNotFoundError:
    s = {}
mark = "claude_widget.py"

# ステータスライン（既存のものは引き継いで表示を変えない）
ours = '"%s" "%s" statusline' % (py, script)
sl = s.get("statusLine")
prev_file = os.path.join(dest, "prev_statusline_command")
if isinstance(sl, dict) and sl.get("command") and mark not in sl["command"]:
    open(prev_file, "w").write(sl["command"])
    print("  既存のステータスラインを引き継ぎます: " + sl["command"])
elif not (isinstance(sl, dict) and mark in sl.get("command", "")):
    if os.path.exists(prev_file):
        os.remove(prev_file)
s["statusLine"] = {"type": "command", "command": ours, "padding": 0}

# フック（稼働状況の記録）
hooks = s.setdefault("hooks", {})
events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "Notification", "Stop", "SessionEnd"]
for ev in events:
    groups = hooks.get(ev, [])
    cleaned = []
    for g in groups:
        hs = [h for h in g.get("hooks", []) if mark not in h.get("command", "")]
        if hs:
            g["hooks"] = hs
            cleaned.append(g)
    entry = {"hooks": [{"type": "command", "command": '"%s" "%s" hook %s' % (py, script, ev), "timeout": 10}]}
    if ev == "PreToolUse":
        entry["matcher"] = "*"
    cleaned.append(entry)
    hooks[ev] = cleaned
os.makedirs(os.path.dirname(path), exist_ok=True)
json.dump(s, open(path, "w"), ensure_ascii=False, indent=2)
PYEOF
ok "Claude Code の設定を更新（バックアップ: ~/.claude/settings.json.bak-claude-widget-*）"

# 5) 5分おきに使用量を取得（Mac が起きている間）
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.claudewidget.poll</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>$DEST/claude_widget.py</string><string>poll</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$DEST/poll.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/com.claudewidget.poll" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
ok "5分おきの自動取得を登録"

# 6) iPhone（Scriptable）用ウィジェット
if [ -d "$SCRIPTABLE" ]; then
  cp "$SRC/Claude Usage.js" "$SCRIPTABLE/Claude Usage.js"
  ok "Scriptable にウィジェットを配置（iCloud 経由で iPhone に同期されます）"
else
  warn "Scriptable の iCloud フォルダがまだありません。"
  echo "   Mac と iPhone の iCloud Drive をオンにし、iPhone に「Scriptable」（無料）を入れて一度開いてから、"
  echo "   このインストーラをもう一度実行してください。"
fi

# 7) メニューバー（SwiftBar・任意）
SB_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
if [ ! -d "/Applications/SwiftBar.app" ] && command -v brew >/dev/null 2>&1; then
  if ask_yes "メニューバー表示用の SwiftBar（無料）を入れますか？"; then
    brew install --cask swiftbar || true
  fi
fi
if [ -d "/Applications/SwiftBar.app" ]; then
  if [ -z "$SB_DIR" ]; then
    SB_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
    defaults write com.ameba.SwiftBar PluginDirectory "$SB_DIR"
  fi
  mkdir -p "$SB_DIR"
  cat > "$SB_DIR/claude.1m.sh" <<EOF
#!/bin/bash
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
exec "$PY" "$DEST/claude_widget.py" swiftbar
EOF
  chmod +x "$SB_DIR/claude.1m.sh"
  if pgrep -xq SwiftBar; then
    open -g "swiftbar://refreshallplugins" 2>/dev/null || true
  else
    open -a SwiftBar 2>/dev/null || true
  fi
  ok "メニューバー表示を設定（SwiftBar）"
else
  echo "  （メニューバー表示は省略しました。使う場合は SwiftBar を入れてから再実行してください）"
fi

# 8) ログイン情報の確認（パスワードは読まないので確認ダイアログは出ません）
if ! /usr/bin/security find-generic-password -s "$KEYCHAIN_SERVICE" >/dev/null 2>&1; then
  echo
  warn "Claude Code のログイン情報がキーチェーンにありません。"
  echo "   Claude のデスクトップアプリだけを使っている場合によく起きます。"
  echo "   次の2つをターミナルで実行し、起動した claude でログイン（Claude のアカウントを選択）してください。"
  echo "     curl -fsSL https://claude.ai/install.sh | bash"
  echo "     ~/.local/bin/claude"
  echo "   ログインできたら /exit で閉じ、このインストーラをもう一度実行してください。"
  echo "   （Claude Code の稼働状況の表示は、ログインしなくても使えます）"
else
  # 9) 初回取得
  echo
  echo "使用量を取得しています…（キーチェーンの確認が出たら「常に許可」を押してください）"
  "$PY" "$DEST/claude_widget.py" poll || true
  "$PY" - "$DEST/state.json" <<'PYEOF'
import json, sys
try:
    s = json.load(open(sys.argv[1]))
except Exception:
    s = {}
u = s.get("usage") or {}
f, w = u.get("five_hour"), u.get("seven_day")
if f or w:
    print("  5時間: %s%%   週間: %s%%" % (f and round(f["pct"]), w and round(w["pct"])))
    for x in u.get("extra") or []:
        print("  %s: %s%%" % (x["label"], round(x["pct"])))
if s.get("error"):
    print("  ! " + s["error"])
PYEOF
fi

echo
ok "完了！ 起動中の Claude Code は、一度終了して起動し直すと稼働状況の記録が始まります。"
echo "   iPhone では、ホーム画面に Scriptable のウィジェットを置き、Script に「Claude Usage」を選んでください。"
