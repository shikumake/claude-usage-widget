#!/bin/bash
# Claude 使用量ウィジェット（非公式）を取り除きます。Claude Code の設定も元に戻します。
#
# 使い方（どちらでも可）:
#   curl -fsSL https://raw.githubusercontent.com/shikumake/claude-usage-widget/main/uninstall.sh | bash
#   bash uninstall.sh
PY="$(command -v python3)"
SETTINGS="$HOME/.claude/settings.json"
DEST="$HOME/.claude-widget"
SCRIPTABLE="$HOME/Library/Mobile Documents/iCloud~dk~simonbs~Scriptable/Documents"

# 自動取得を止める
launchctl bootout "gui/$(id -u)/com.claudewidget.poll" 2>/dev/null
rm -f "$HOME/Library/LaunchAgents/com.claudewidget.poll.plist"

# メニューバー（SwiftBar）のプラグインを削除
SB_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null)"
[ -n "$SB_DIR" ] && rm -f "$SB_DIR/claude.1m.sh"

# Claude Code の設定から、このツールのステータスラインとフックだけを外す
if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.bak-claude-widget-uninstall-$(date +%Y%m%d%H%M%S)"
  "$PY" - "$SETTINGS" "$DEST/prev_statusline_command" <<'PYEOF'
import json, os, sys
path, prev = sys.argv[1], sys.argv[2]
s = json.load(open(path))
mark = "claude_widget.py"
sl = s.get("statusLine")
if isinstance(sl, dict) and mark in sl.get("command", ""):
    if os.path.exists(prev) and open(prev).read().strip():
        s["statusLine"] = {"type": "command", "command": open(prev).read().strip()}
    else:
        s.pop("statusLine")
hooks = s.get("hooks", {})
for ev in list(hooks):
    out = []
    for g in hooks[ev]:
        hs = [h for h in g.get("hooks", []) if mark not in h.get("command", "")]
        if hs:
            g["hooks"] = hs
            out.append(g)
    if out:
        hooks[ev] = out
    else:
        del hooks[ev]
if not hooks:
    s.pop("hooks", None)
json.dump(s, open(path, "w"), ensure_ascii=False, indent=2)
PYEOF
fi

# 保存していたデータを削除
[ -d "$SCRIPTABLE" ] && rm -f "$SCRIPTABLE/claude-status.json"
[ -n "$DEST" ] && [ -d "$DEST" ] && rm -rf "$DEST"

echo "削除しました。"
echo "iPhone の Scriptable にある「Claude Usage」と、ホーム画面のウィジェットは手動で削除してください。"
