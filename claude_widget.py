#!/usr/bin/env python3
"""Claude 使用量 & Claude Code 稼働状況コレクター

サブコマンド:
  poll              使用量をAnthropicに問い合わせて保存（launchdから5分おき）
  statusline        Claude Codeのステータスラインから使用量を受け取って保存
  hook              Claude Codeのフックから稼働状況を受け取って保存
  swiftbar          SwiftBar（メニューバー）用の表示を出力
  show              現在の状態をJSONで表示（確認用）

保存先:
  ~/.claude-widget/state.json                         （Mac内）
  ~/Library/Mobile Documents/iCloud~dk~simonbs~Scriptable/Documents/claude-status.json
                                                      （iCloud経由でiPhoneのScriptableへ）
"""
import datetime as dt
import fcntl
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
BASE = os.environ.get("CLAUDE_WIDGET_DIR", os.path.join(HOME, ".claude-widget"))
STATE = os.path.join(BASE, "state.json")
LOCK = os.path.join(BASE, ".lock")
PREV_STATUSLINE = os.path.join(BASE, "prev_statusline_command")
ICLOUD_DIRS = [
    os.path.join(HOME, "Library/Mobile Documents/iCloud~dk~simonbs~Scriptable/Documents"),
]
EXPORT_NAME = "claude-status.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"
SESSION_TTL = 12 * 3600          # 12時間更新のないセッションは消す
WORKING_STALE = 30 * 60          # 30分更新のない「作業中」は「不明」扱い


# ---------------------------------------------------------------- utilities
def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(v):
    """ISO文字列 / epoch秒 / epochミリ秒 → aware datetime"""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            x = float(v)
            if x > 1e12:
                x /= 1000.0
            return dt.datetime.fromtimestamp(x, dt.timezone.utc)
        s = str(v).strip()
        if s.replace(".", "", 1).isdigit():
            return parse_time(float(s))
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        t = dt.datetime.fromisoformat(s)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t
    except Exception:
        return None


def norm_window(v):
    """色々な形の使用量データを {pct, resets_at} にそろえる"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return {"pct": round(float(v), 1), "resets_at": None}
    if not isinstance(v, dict):
        return None
    pct = None
    for k in ("utilization", "used_percentage", "used_percent", "percentage", "percent", "usage"):
        if isinstance(v.get(k), (int, float)):
            pct = float(v[k])
            break
    if pct is None:
        return None
    reset = None
    for k in ("resets_at", "reset_at", "resetsAt", "reset_time", "resets"):
        if k in v:
            reset = parse_time(v[k])
            break
    return {"pct": round(pct, 1), "resets_at": iso(reset) if reset else None}


LABELS = {
    "five_hour": "5時間",
    "seven_day": "週間",
    "seven_day_opus": "Opus 週",
    "seven_day_sonnet": "Sonnet 週",
    "seven_day_fable": "Fable 週",
    "seven_day_mythos": "Mythos 週",
    "seven_day_oauth_apps": "外部アプリ 週",
}


def label_for(key):
    if key in LABELS:
        return LABELS[key]
    if key.startswith("seven_day_"):
        return key[len("seven_day_"):].replace("_", " ").title() + " 週"
    return key


def normalize_usage(raw, source):
    """APIまたはステータスラインの rate limit データを共通形式へ"""
    if not isinstance(raw, dict):
        return None
    out = {"five_hour": None, "seven_day": None, "extra": [], "source": source,
           "fetched_at": iso(now())}
    for key, val in raw.items():
        w = norm_window(val)
        if w is None:
            continue
        if key in ("five_hour", "seven_day"):
            out[key] = w
        elif key.startswith("seven_day_") or key.startswith("five_hour_"):
            w["key"] = key
            w["label"] = label_for(key)
            out["extra"].append(w)
    # 新しい形式: limits 一覧（モデル別の週上限は weekly_scoped で入る。例: Fable）
    for x in raw.get("limits") or []:
        if not isinstance(x, dict):
            continue
        w = norm_window(x)
        if w is None:
            continue
        kind = x.get("kind")
        if kind == "session":
            out["five_hour"] = out["five_hour"] or w
        elif kind == "weekly_all":
            out["seven_day"] = out["seven_day"] or w
        else:
            scope = x.get("scope") if isinstance(x.get("scope"), dict) else {}
            name = None
            for part in ("model", "surface"):
                p = scope.get(part)
                if isinstance(p, dict) and p.get("display_name"):
                    name = p["display_name"]
                    break
                if isinstance(p, str) and p:
                    name = p
                    break
            name = name or kind or "その他"
            label = "%s 週" % name if x.get("group") == "weekly" else str(name)
            if any(e["label"] == label for e in out["extra"]):
                continue
            w["key"] = "limit_%s" % name
            w["label"] = label
            out["extra"].append(w)
    if out["five_hour"] is None and out["seven_day"] is None:
        return None
    return out


# ------------------------------------------------------------------- state
class Locked:
    def __enter__(self):
        os.makedirs(BASE, exist_ok=True)
        self.f = open(LOCK, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"usage": None, "sessions": {}, "error": None}


def atomic_write(path, data):
    # 一時ファイルはiCloudフォルダの外（BASE）に作り、iCloudに余計なファイルを同期させない
    tmp = os.path.join(BASE, "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.remove(tmp)


def prune(state):
    t = now()
    sessions = state.get("sessions") or {}
    for sid in list(sessions):
        u = parse_time(sessions[sid].get("updated_at"))
        if u is None or (t - u).total_seconds() > SESSION_TTL:
            del sessions[sid]
    state["sessions"] = sessions


def export(state):
    """ウィジェット用の軽いJSONをiCloudへ書き出す"""
    prune(state)
    t = now()
    sessions = []
    for sid, s in (state.get("sessions") or {}).items():
        st = s.get("status", "idle")
        u = parse_time(s.get("updated_at"))
        if st == "working" and u and (t - u).total_seconds() > WORKING_STALE:
            st = "unknown"
        sessions.append({"id": sid[:8], "project": s.get("project", "?"), "status": st,
                         "updated_at": s.get("updated_at"), "message": s.get("message")})
    order = {"waiting": 0, "working": 1, "done": 2, "unknown": 3, "idle": 4}
    sessions.sort(key=lambda x: (order.get(x["status"], 9), x["project"]))
    counts = {}
    for s in sessions:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    out = {"updated_at": iso(t), "usage": state.get("usage"), "sessions": sessions,
           "counts": counts, "error": state.get("error"), "host": os.uname().nodename}
    # iCloud へは「表示が変わったとき」か「前回から一定時間たったとき」だけ書き出す。
    # ツールを使うたびに書き換えると iPhone 側のダウンロードが追いつかなくなるため。
    sig = export_signature(out)
    meta = state.get("_icloud") or {}
    last = parse_time(meta.get("at"))
    if sig != meta.get("sig") or last is None or (t - last).total_seconds() >= ICLOUD_MIN_INTERVAL:
        wrote = False
        for d in ICLOUD_DIRS:
            if os.path.isdir(d):
                try:
                    write_in_place(os.path.join(d, EXPORT_NAME), out)
                    wrote = True
                except Exception:
                    pass
        if wrote:
            state["_icloud"] = {"sig": sig, "at": iso(t)}
    atomic_write(STATE, state)
    return out


ICLOUD_MIN_INTERVAL = 4 * 60   # 表示が変わらなくても、この間隔を過ぎたら書き出す（古く見えないように）


def export_signature(out):
    """ウィジェットの表示に関係する部分だけ（取得時刻など毎回変わる値は除く）"""
    u = out.get("usage") or {}

    def win(w):
        return w and (w.get("pct"), w.get("resets_at"), w.get("label"))
    sig = {
        "usage": [win(u.get("five_hour")), win(u.get("seven_day"))] + [win(x) for x in u.get("extra") or []],
        "sessions": [(s["project"], s["status"], s.get("message")) for s in out.get("sessions") or []],
        "error": out.get("error"),
    }
    return json.dumps(sig, ensure_ascii=False, sort_keys=True)


# iCloud の競合を解消する（macOS 標準の JavaScript for Automation で NSFileVersion を使う）。
# 競合が残ると、iPhone 側で古い版が表示され続けることがある。
RESOLVE_JXA = r"""
ObjC.import('Foundation');
function run(argv) {
  var url = $.NSURL.fileURLWithPath(argv[0]);
  var list = $.NSFileVersion.unresolvedConflictVersionsOfItemAtURL(url);
  var n = (list && !list.isNil()) ? list.count : 0;
  for (var i = 0; i < n; i++) { list.objectAtIndex(i).resolved = true; }
  if (n > 0) { $.NSFileVersion.removeOtherVersionsOfItemAtURLError(url, $()); }
  return String(n);
}
"""


def resolve_icloud_conflicts():
    """Mac の今の版を正として、iCloud 上の競合している古い版を片付ける。片付けた数を返す"""
    total = 0
    for d in ICLOUD_DIRS:
        p = os.path.join(d, EXPORT_NAME)
        if not os.path.exists(p):
            continue
        try:
            r = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", RESOLVE_JXA, p],
                               capture_output=True, text=True, timeout=20)
            total += int((r.stdout or "0").strip() or 0)
        except Exception:
            pass
    return total


def write_in_place(path, data):
    """iCloud のファイルは置き換えず、同じファイルに上書きする（iCloud から見て同じファイルの更新になる）"""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    with open(path, "w") as f:
        f.write(text)


def update_usage(usage=None, error=None, error_only_if_stale=False):
    with Locked():
        st = load()
        if usage:
            prev = st.get("usage") or {}
            # APIの方が正確なので、直近2分以内にAPIで取れていればステータスラインで上書きしない
            if (usage["source"] == "statusline" and prev.get("source") == "api"):
                pt = parse_time(prev.get("fetched_at"))
                if pt and (now() - pt).total_seconds() < 120:
                    usage = None
            if usage:
                st["usage"] = usage
                st["error"] = None
        if error is not None:
            fresh = False
            u = st.get("usage") or {}
            ft = parse_time(u.get("fetched_at"))
            if ft and (now() - ft).total_seconds() < 900:
                fresh = True
            if not (error_only_if_stale and fresh):
                st["error"] = error
        export(st)


# -------------------------------------------------------------------- poll
def read_token():
    try:
        raw = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        raw = ""
    if not raw:
        # Linux等では ~/.claude/.credentials.json に保存される
        p = os.path.join(HOME, ".claude", ".credentials.json")
        if os.path.exists(p):
            raw = open(p).read()
    if not raw:
        return None, "Claude Codeのログイン情報が見つかりません（ターミナルで claude を起動してログインしてください）"
    try:
        data = json.loads(raw)
        o = data.get("claudeAiOauth") or data
        tok = o.get("accessToken")
        exp = parse_time(o.get("expiresAt"))
        # 期限切れ（または5分以内に切れる）
        if exp and (exp - now()).total_seconds() < 300:
            return None, EXPIRED_MSG
        return tok, None
    except Exception:
        return None, "ログイン情報を読めませんでした"


EXPIRED_MSG = "ログイン情報の期限切れ（ターミナルで claude を一度起動すると直ります）"
REFRESH_MARK = os.path.join(BASE, ".last_refresh")
NO_REFRESH = os.path.join(BASE, "no_auto_refresh")   # このファイルを置くと自動更新しない
REFRESH_INTERVAL = 30 * 60                           # 自動更新を試す最短の間隔


def find_claude():
    for p in (os.path.join(HOME, ".local/bin/claude"), "/opt/homebrew/bin/claude",
              "/usr/local/bin/claude", os.path.join(HOME, ".claude/local/claude")):
        if os.access(p, os.X_OK):
            return p
    return None


def refresh_via_cli():
    """期限切れのログイン情報を、公式の claude コマンドに更新させる。
    claude は通信の前に自分でログイン情報を更新するので、ごく短いやりとりを1回だけ行う。
    （このツール自身はキーチェーンを書き換えない）"""
    if os.path.exists(NO_REFRESH):
        return False
    claude = find_claude()
    if not claude:
        return False
    try:
        if time.time() - os.path.getmtime(REFRESH_MARK) < REFRESH_INTERVAL:
            return False
    except OSError:
        pass
    os.makedirs(BASE, exist_ok=True)
    open(REFRESH_MARK, "w").close()
    env = dict(os.environ, CLAUDE_WIDGET_INTERNAL="1")
    try:
        subprocess.run([claude, "-p", "ok", "--max-turns", "1", "--model", "haiku"],
                       cwd=BASE, env=env, capture_output=True, text=True, timeout=120)
        return True
    except Exception:
        return False


def ssl_context():
    """python.org版Pythonは証明書を持たないことがあるので、macOS標準の証明書も使う"""
    ctx = ssl.create_default_context()
    if os.path.exists("/etc/ssl/cert.pem"):
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


def cmd_poll():
    resolve_icloud_conflicts()
    tok, err = read_token()
    if not tok and err == EXPIRED_MSG and refresh_via_cli():
        tok, err = read_token()
    if not tok:
        update_usage(error=err, error_only_if_stale=True)
        return
    fetch_usage(tok, retry=True)


def fetch_usage(tok, retry=False):
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + tok,
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
        "User-Agent": "claude-widget/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as r:
            raw = json.loads(r.read().decode())
        usage = normalize_usage(raw, "api")
        if usage:
            update_usage(usage=usage)
        else:
            update_usage(error="使用量の形式が想定外です", error_only_if_stale=True)
    except urllib.error.HTTPError as e:
        msg = "使用量の取得に失敗 (HTTP %d)" % e.code
        if e.code == 401:
            # 期限前に無効になった場合も、一度だけ更新を試す
            if retry and refresh_via_cli():
                tok2, _ = read_token()
                if tok2 and tok2 != tok:
                    return fetch_usage(tok2)
            msg = EXPIRED_MSG
        update_usage(error=msg, error_only_if_stale=True)
    except Exception as e:
        update_usage(error="使用量の取得に失敗: %s" % type(e).__name__, error_only_if_stale=True)


# -------------------------------------------------------------- statusline
def cmd_statusline():
    data = sys.stdin.read()
    out_text = None
    # 以前のステータスラインがあれば、そのまま表示を引き継ぐ
    if os.path.exists(PREV_STATUSLINE):
        prev = open(PREV_STATUSLINE).read().strip()
        if prev:
            try:
                out_text = subprocess.run(prev, shell=True, input=data, capture_output=True,
                                          text=True, timeout=10).stdout
            except Exception:
                out_text = None
    try:
        j = json.loads(data)
    except Exception:
        j = {}
    rl = j.get("rate_limits") if isinstance(j, dict) else None
    usage = normalize_usage(rl, "statusline") if rl else None
    if usage:
        try:
            update_usage(usage=usage)
        except Exception:
            pass
    if out_text is not None:
        sys.stdout.write(out_text)
        return
    # 既定のステータスライン
    model = ((j.get("model") or {}).get("display_name")) if isinstance(j, dict) else None
    cwd = ((j.get("workspace") or {}).get("current_dir") or j.get("cwd") or "") if isinstance(j, dict) else ""
    parts = []
    if model:
        parts.append(model)
    if cwd:
        parts.append(os.path.basename(cwd.rstrip("/")) or cwd)
    if usage:
        if usage.get("five_hour"):
            parts.append("5h %d%%" % round(usage["five_hour"]["pct"]))
        if usage.get("seven_day"):
            parts.append("週 %d%%" % round(usage["seven_day"]["pct"]))
    sys.stdout.write(" · ".join(parts))


# -------------------------------------------------------------------- hook
EVENT_STATUS = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "SubagentStop": "working",
    "PreCompact": "working",
    "Notification": "waiting",
    "Stop": "done",
}


def cmd_hook():
    # ログイン情報の自動更新のために起動した claude は、セッションとして記録しない
    if os.environ.get("CLAUDE_WIDGET_INTERNAL"):
        return
    try:
        j = json.loads(sys.stdin.read() or "{}")
    except Exception:
        j = {}
    ev = j.get("hook_event_name") or (sys.argv[2] if len(sys.argv) > 2 else "")
    sid = j.get("session_id") or "unknown"
    cwd = j.get("cwd") or os.getcwd()
    with Locked():
        st = load()
        sessions = st.setdefault("sessions", {})
        if ev == "SessionEnd":
            sessions.pop(sid, None)
        else:
            status = EVENT_STATUS.get(ev)
            if status:
                s = sessions.setdefault(sid, {})
                s["project"] = os.path.basename(cwd.rstrip("/")) or cwd
                s["status"] = status
                s["updated_at"] = iso(now())
                s["message"] = (j.get("message") or "")[:80] if ev == "Notification" else None
        export(st)
    # フックは何も出力せず正常終了（Claude Codeの動作に影響させない）


# ---------------------------------------------------------------- swiftbar
STATUS_JA = {"working": "作業中", "waiting": "入力待ち", "done": "完了", "idle": "待機",
             "unknown": "不明"}


def fmt_left(t):
    r = parse_time(t)
    if not r:
        return ""
    s = int((r - now()).total_seconds())
    if s <= 0:
        return "リセット済み"
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return "%d日%d時間後にリセット" % (d, h)
    if h:
        return "%d時間%d分後にリセット" % (h, m)
    return "%d分後にリセット" % m


def color(p):
    if p is None:
        return ""
    return "#E5484D" if p >= 90 else "#F5A623" if p >= 70 else ""


def cmd_swiftbar():
    with Locked():
        out = export(load())
    u = out.get("usage") or {}
    f = (u.get("five_hour") or {}).get("pct")
    w = (u.get("seven_day") or {}).get("pct")
    c = out.get("counts", {})
    dot = "🟠" if c.get("waiting") else "🟢" if c.get("working") else ""
    title = "✳︎ %s · %s" % ("%d%%" % round(f) if f is not None else "–",
                             "%d%%" % round(w) if w is not None else "–")
    print((dot + " " if dot else "") + title + ("| color=%s" % color(max(f or 0, w or 0)) if color(max(f or 0, w or 0)) else ""))
    print("---")
    for key, name in (("five_hour", "5時間"), ("seven_day", "週間")):
        x = u.get(key)
        if x:
            line = "%s  %d%%  （%s）" % (name, round(x["pct"]), fmt_left(x.get("resets_at")))
            if color(x["pct"]):
                line += " | color=%s" % color(x["pct"])
            print(line)
    for x in u.get("extra") or []:
        print("%s  %d%%  （%s）| size=12" % (x["label"], round(x["pct"]), fmt_left(x.get("resets_at"))))
    if out.get("error"):
        print("⚠️ %s | color=#F5A623 size=12" % out["error"])
    print("---")
    ss = out.get("sessions") or []
    if not ss:
        print("Claude Code: 稼働中のセッションなし")
    for s in ss:
        icon = {"working": "🟢", "waiting": "🟠", "done": "✅", "idle": "⚪️", "unknown": "❔"}.get(s["status"], "•")
        line = "%s %s — %s" % (icon, s["project"], STATUS_JA.get(s["status"], s["status"]))
        print(line)
        if s.get("message"):
            print("-- %s | size=11" % s["message"].replace("|", "/"))
    print("---")
    ft = parse_time(u.get("fetched_at"))
    if ft:
        print("使用量の取得: %s | size=11" % ft.astimezone().strftime("%H:%M"))
    print("今すぐ更新 | bash=%s param1=%s param2=poll terminal=false refresh=true" % (sys.executable, os.path.abspath(__file__)))
    print("claude.ai の使用量ページ | href=https://claude.ai/settings/usage")


def cmd_show():
    with Locked():
        print(json.dumps(export(load()), ensure_ascii=False, indent=2))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    try:
        {"poll": cmd_poll, "statusline": cmd_statusline, "hook": cmd_hook,
         "swiftbar": cmd_swiftbar, "show": cmd_show}.get(cmd, cmd_show)()
    except Exception as e:
        # フックやステータスラインでエラーを出してClaude Codeを邪魔しない
        if cmd in ("hook", "statusline"):
            return
        raise


if __name__ == "__main__":
    main()
