// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: deep-brown; icon-glyph: asterisk;

// Claude 使用量 & Claude Code 稼働状況ウィジェット
// データ: iCloud Drive/Scriptable/claude-status.json（Macが5分おきに更新）
// ウィジェットのパラメータに「残り」と入れると、使用率ではなく残り％で表示します。

const ACCENT = new Color("#D97757");
const BG = Color.dynamic(new Color("#F5F4EE"), new Color("#262624"));
const FG = Color.dynamic(new Color("#1F1E1D"), new Color("#F5F4EE"));
const SUB = Color.dynamic(new Color("#6B6A65"), new Color("#A3A29C"));
const TRACK = Color.dynamic(new Color("#E3E1D8"), new Color("#3A3936"));
const WARN = new Color("#E5484D");
const STATUS = {
  working: { ja: "作業中", color: new Color("#3FB950") },
  waiting: { ja: "入力待ち", color: new Color("#F5A623") },
  done: { ja: "完了", color: new Color("#8B949E") },
  idle: { ja: "待機", color: new Color("#8B949E") },
  unknown: { ja: "不明", color: new Color("#8B949E") },
};

const param = (args.widgetParameter || "").trim();
const REMAIN = param.includes("残り") || param.toLowerCase().includes("remain");

let loadError = "";

async function loadData() {
  const icloud = FileManager.iCloud();
  const local = FileManager.local();
  const dir = icloud.documentsDirectory();
  const path = icloud.joinPath(dir, "claude-status.json");
  const cache = local.joinPath(local.documentsDirectory(), "claude-status-cache.json");
  try {
    // まだダウンロードされていないファイルは「.claude-status.json.icloud」として見えることがある
    const names = icloud.listContents(dir);
    if (!icloud.fileExists(path) && !names.some(n => n.includes("claude-status"))) {
      throw new Error("iPhoneにデータが届いていません（iCloud Driveの同期待ち）");
    }
    await icloud.downloadFileFromiCloud(path);
    const text = icloud.readString(path);
    if (!text) throw new Error("データを読めませんでした（ダウンロード中）");
    const data = JSON.parse(text);
    local.writeString(cache, text);
    return data;
  } catch (e) {
    loadError = e.message || String(e);
  }
  // 読めなかったときは、前回読めたデータを表示する
  try {
    if (local.fileExists(cache)) return JSON.parse(local.readString(cache));
  } catch (e) {}
  return null;
}

function pctOf(w) {
  if (!w || typeof w.pct !== "number") return null;
  return REMAIN ? Math.max(0, 100 - w.pct) : w.pct;
}

function left(iso) {
  if (!iso) return "";
  let s = Math.floor((new Date(iso) - new Date()) / 1000);
  if (s <= 0) return "まもなく";
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d) return `${d}日${h}時間`;
  if (h) return `${h}時間${m}分`;
  return `${m}分`;
}

function hhmm(iso) {
  const d = new Date(iso);
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function barImage(used, width, height = 5) {
  const ctx = new DrawContext();
  ctx.size = new Size(width, height);
  ctx.opaque = false;
  ctx.respectScreenScale = true;
  const r = height / 2;
  let p = new Path();
  p.addRoundedRect(new Rect(0, 0, width, height), r, r);
  ctx.addPath(p);
  ctx.setFillColor(TRACK);
  ctx.fillPath();
  const v = Math.max(0, Math.min(100, used || 0));
  if (v > 0) {
    p = new Path();
    p.addRoundedRect(new Rect(0, 0, Math.max(height, (width * v) / 100), height), r, r);
    ctx.addPath(p);
    ctx.setFillColor(v >= 90 ? WARN : ACCENT);
    ctx.fillPath();
  }
  return ctx.getImage();
}

function addText(stack, text, size, color, bold = false) {
  const t = stack.addText(text);
  t.font = bold ? Font.boldRoundedSystemFont(size) : Font.systemFont(size);
  t.textColor = color;
  t.lineLimit = 1;
  t.minimumScaleFactor = 0.6;
  return t;
}

function header(w, data) {
  const h = w.addStack();
  h.centerAlignContent();
  const icon = h.addText("✳︎");
  icon.font = Font.boldSystemFont(16);
  icon.textColor = ACCENT;
  h.addSpacer(6);
  addText(h, "Claude", 16, FG, true);
  h.addSpacer();
  const stale = data && (new Date() - new Date(data.updated_at)) / 60000 > 20;
  if (stale) addText(h, `更新 ${hhmm(data.updated_at)}`, 11, WARN);
  else addText(h, REMAIN ? "残り" : "使用", 12, SUB);
}

function windowColumn(parent, title, win, width, big = 32) {
  const c = parent.addStack();
  c.layoutVertically();
  addText(c, title, 12, SUB);
  c.addSpacer(2);
  const row = c.addStack();
  row.bottomAlignContent();
  const p = pctOf(win);
  addText(row, p === null ? "–" : String(Math.round(p)), big, FG, true);
  row.addSpacer(2);
  addText(row, "%", Math.round(big * 0.45), SUB);
  c.addSpacer(4);
  const img = c.addImage(barImage(win ? win.pct : 0, width));
  img.imageSize = new Size(width, 5);
  c.addSpacer(4);
  addText(c, win && win.resets_at ? `↻ ${left(win.resets_at)}` : " ", 11, SUB);
  return c;
}

function statusSummary(data) {
  const c = (data && data.counts) || {};
  const parts = [];
  for (const k of ["waiting", "working", "done"]) if (c[k]) parts.push({ k, n: c[k] });
  return parts;
}

function codeRow(w, data, withNames) {
  const r = w.addStack();
  r.centerAlignContent();
  addText(r, "Claude Code", 12, SUB);
  r.addSpacer(8);
  const parts = statusSummary(data);
  if (!parts.length) {
    addText(r, (data && data.sessions && data.sessions.length) ? "待機中" : "停止中", 12, SUB);
  } else {
    parts.forEach((x, i) => {
      if (i) r.addSpacer(8);
      addText(r, "●", 10, STATUS[x.k].color);
      r.addSpacer(3);
      addText(r, `${STATUS[x.k].ja} ${x.n}`, 12, FG, true);
    });
  }
  r.addSpacer();
  if (withNames && data && data.sessions && data.sessions.length) {
    const s = data.sessions[0];
    addText(r, s.project, 11, SUB);
  }
}

function extraRow(w, x) {
  const r = w.addStack();
  r.centerAlignContent();
  addText(r, x.label, 12, SUB);
  r.addSpacer(6);
  addText(r, x.resets_at ? `↻ ${left(x.resets_at)}` : "", 11, SUB);
  r.addSpacer();
  const p = pctOf(x);
  addText(r, p === null ? "–" : `${Math.round(p)}%`, 14, FG, true);
}

function sep(w) {
  w.addSpacer(6);
  const img = w.addImage(barImage(0, 300, 1));
  img.imageSize = new Size(300, 1);
  w.addSpacer(6);
}

async function build() {
  const data = await loadData();
  const fam = config.widgetFamily || "medium";
  const w = new ListWidget();
  w.backgroundColor = BG;
  w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
  w.url = "https://claude.ai/settings/usage";
  const u = (data && data.usage) || {};

  // ロック画面
  if (fam === "accessoryRectangular") {
    w.backgroundColor = Color.clear();
    const f = pctOf(u.five_hour), s = pctOf(u.seven_day);
    const t1 = w.addText(`✳︎ 5h ${f === null ? "–" : Math.round(f)}% · 週 ${s === null ? "–" : Math.round(s)}%`);
    t1.font = Font.boldSystemFont(14);
    const t2 = w.addText(u.five_hour && u.five_hour.resets_at ? `↻ ${left(u.five_hour.resets_at)}` : "");
    t2.font = Font.systemFont(12);
    const parts = statusSummary(data);
    const t3 = w.addText("CC: " + (parts.length ? parts.map(x => `${STATUS[x.k].ja}${x.n}`).join(" ") : "停止中"));
    t3.font = Font.systemFont(12);
    return w;
  }
  if (fam === "accessoryCircular" || fam === "accessoryInline") {
    w.backgroundColor = Color.clear();
    const f = pctOf(u.five_hour);
    const t = w.addText(fam === "accessoryInline" ? `✳︎ 5h ${f === null ? "–" : Math.round(f)}%` : `${f === null ? "–" : Math.round(f)}%`);
    t.font = Font.boldRoundedSystemFont(fam === "accessoryInline" ? 13 : 18);
    t.centerAlignText();
    return w;
  }

  w.setPadding(14, 16, 12, 16);
  header(w, data);
  w.addSpacer(8);

  if (!data) {
    addText(w, "データがまだありません", 13, FG, true);
    w.addSpacer(4);
    const t = w.addText(loadError || "Macでインストールを実行し、Claude Codeを一度起動してください。");
    t.font = Font.systemFont(11); t.textColor = SUB;
    return w;
  }

  if (fam === "small") {
    const row = w.addStack();
    windowColumn(row, "5時間", u.five_hour, 120, 28);
    w.addSpacer(6);
    const r2 = w.addStack();
    r2.centerAlignContent();
    const s = pctOf(u.seven_day);
    addText(r2, "週間", 11, SUB); r2.addSpacer(); addText(r2, s === null ? "–" : `${Math.round(s)}%`, 13, FG, true);
    w.addSpacer(4);
    const parts = statusSummary(data);
    const r3 = w.addStack(); r3.centerAlignContent();
    if (parts.length) { addText(r3, "●", 9, STATUS[parts[0].k].color); r3.addSpacer(3); addText(r3, `${STATUS[parts[0].k].ja} ${parts[0].n}`, 11, FG); }
    else addText(r3, "Claude Code 停止中", 11, SUB);
    return w;
  }

  const cols = w.addStack();
  windowColumn(cols, "5時間", u.five_hour, 125);
  cols.addSpacer();
  windowColumn(cols, "週間", u.seven_day, 125);

  sep(w);
  if (fam === "large" || fam === "extraLarge") {
    for (const x of (u.extra || [])) { extraRow(w, x); w.addSpacer(6); }
    codeRow(w, data, false);
    w.addSpacer(6);
    for (const s of (data.sessions || []).slice(0, 5)) {
      const r = w.addStack(); r.centerAlignContent();
      const st = STATUS[s.status] || STATUS.unknown;
      addText(r, "●", 9, st.color); r.addSpacer(6);
      addText(r, s.project, 13, FG, true); r.addSpacer();
      addText(r, st.ja, 12, SUB);
      if (s.message) { w.addSpacer(1); const m = w.addText("   " + s.message); m.font = Font.systemFont(10); m.textColor = SUB; m.lineLimit = 1; }
      w.addSpacer(4);
    }
    if (data.error) { w.addSpacer(4); addText(w, "⚠︎ " + data.error, 10, WARN); }
    w.addSpacer();
  } else {
    // medium: 稼働中のセッションがあればClaude Code、なければ追加の上限（Fable週など）
    const parts = statusSummary(data);
    if (parts.length || !(u.extra && u.extra.length)) codeRow(w, data, true);
    else extraRow(w, u.extra[0]);
  }
  return w;
}

const widget = await build();
if (config.runsInWidget) Script.setWidget(widget);
else await widget.presentMedium();
Script.complete();
