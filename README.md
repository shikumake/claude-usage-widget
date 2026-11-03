# Claude 使用量ウィジェット（非公式）

Claude（Pro / Max）の**使用量**と、**Claude Code の稼働状況**を、iPhone と Mac のウィジェットに表示します。

- 使用量：5時間・週間・モデル別の週上限（Fable 週など）と、リセットまでの時間
- Claude Code：作業中／入力待ち／完了

> **非公式ツールです。** Anthropic とは関係ありません。使用量の取得には公開されていない仕組みを使っているため、仕様変更で動かなくなる可能性があります。

## 必要なもの
- Mac（macOS）と iPhone
- Claude の Pro / Max プラン
- Claude Code（ターミナル版。デスクトップアプリだけの人も、下の手順で一度ログインすれば使えます）
- iPhone アプリ「[Scriptable](https://apps.apple.com/app/scriptable/id1405459188)」（無料）
- Mac と iPhone の **iCloud Drive がオン**になっていること

## インストール

### 1. Mac で1行実行
ターミナルで次を実行します。

```bash
curl -fsSL https://raw.githubusercontent.com/shikumake/claude-usage-widget/main/install.sh | bash
```

- キーチェーンの確認が出たら「**常に許可**」を押してください。
- 起動中の Claude Code は、一度終了して起動し直してください。

**Claude Code に頼む方法**：Claude Code に「https://github.com/shikumake/claude-usage-widget の README を読んでインストールして」と頼むと、インストールからエラー対応まで進めてくれます。

### 2. iPhone にウィジェットを置く
1. App Store で **Scriptable** を入れて一度開きます（Mac でインストールを実行する前に入れておくと確実です）。
2. ホーム画面を長押し →「編集」→「ウィジェットを追加」→「Scriptable」→ 好きなサイズを追加します。
3. 置いたウィジェットを長押し →「ウィジェットを編集」→ Script で「**Claude Usage**」を選びます。
   - Parameter に「残り」と入れると、残りの％で表示します（空欄なら使用量）。
   - Parameter に「ダーク」または「ライト」と入れると、iPhone の設定に関係なくその色で表示します（空欄なら iPhone のライト／ダークに自動で合わせます）。「残り ダーク」のように組み合わせもできます。
   - ロック画面（長方形・円形）にも置けます。

### 3. 自動更新を設定する（おすすめ）
ホーム画面のウィジェットは、iOS の都合で新しいデータを取り込めず、古い表示のままになることがあります。「ショートカット」アプリのオートメーションで、よく開くアプリ（LINE・X・Safari など）を開いたときに裏でデータを取り込むようにしておくと、いつも新しい表示になります。

1. 「ショートカット」→「オートメーション」→「＋」→ きっかけに「App」を選び、よく開くアプリの「開いている」を選ぶ
2. アクションに Scriptable の「**Run Script**」を追加し、Script に「Claude Usage」を選ぶ
3. 「Run In App」と「実行時に表示」をオフ、「すぐに実行」を選び、「実行時に通知」をオフ

### メニューバー表示（任意）
[SwiftBar](https://github.com/swiftbar/SwiftBar) が入っていれば、メニューバーに使用量と稼働中のセッションを表示します。Homebrew がある場合は、インストール中に導入するか聞かれます。

## 仕組み
| 情報 | 取り方 | 更新 |
|---|---|---|
| 使用量 | Claude Code のログイン情報で、`/usage` と同じ取得先に問い合わせ | 5分おき（Mac が起きている間） |
| Claude Code の稼働状況 | Claude Code のフック | すぐ |

データは Mac の `~/.claude-widget/state.json` と、iCloud Drive の Scriptable フォルダ（`claude-status.json`）に保存され、iCloud 経由で iPhone に届きます。

## セキュリティとプライバシー
- ログイン情報は、Mac のキーチェーン（「Claude Code-credentials」）から読むだけです。保存も書き換えもしません。
- 通信するのは **`api.anthropic.com`（Anthropic）だけ**です。ほかのサーバーには何も送りません。
- iCloud に保存するのは、使用率・リセット時刻・プロジェクト名・稼働状況だけです。ログイン情報は含みません。
- **ログイン情報の自動更新**：ログイン情報は数時間で期限が切れます。期限が切れていたら、公式の `claude` コマンドに短いやりとり（Haiku で「ok」と返すだけ）を1回させて、Claude Code 自身に更新させます。このツールがキーチェーンを書き換えることはありません。使用量への影響はごくわずかです。止めたい場合は `touch ~/.claude-widget/no_auto_refresh` を実行してください。
- コードはすべてこのリポジトリで確認できます。

## 変更するファイル
- `~/.claude/settings.json`：ステータスラインとフックを追加します（変更前にバックアップを作ります。既存のステータスラインの表示は引き継ぎます）
- `~/.claude-widget/`：本体とデータ
- `~/Library/LaunchAgents/com.claudewidget.poll.plist`：5分おきの取得
- iCloud Drive の Scriptable フォルダ：`Claude Usage.js` と `claude-status.json`

## 困ったとき
| 症状 | 対処 |
|---|---|
| 「Claude Code のログイン情報が見つかりません」 | Claude のデスクトップアプリだけを使っている場合に起きます。ターミナルで `curl -fsSL https://claude.ai/install.sh \| bash` → `~/.local/bin/claude` を実行してログインし、インストーラをもう一度実行してください |
| 「ログイン情報の期限切れ」 | 通常は自動で更新されます。続く場合は、ターミナルで `claude` を一度起動して `/exit` で閉じてください |
| 「使用量の取得に失敗: URLError」 | 通常はインストーラが対処します。直らない場合は Issue で教えてください |
| iPhone に「データがまだありません」 | Scriptable アプリで「Claude Usage」を一度タップして実行し、ウィジェットを置き直してください |
| Scriptable の iCloud フォルダがない | Mac と iPhone の iCloud Drive をオンにして、iPhone で Scriptable を開いてから、インストーラを再実行してください |
| ウィジェットの数値が古い | Mac がスリープ中は更新されません。Mac が起きているのに古いままなら、Scriptable アプリを一度開くと新しくなります。毎回開かなくて済むよう「3. 自動更新を設定する」をおすすめします |

状態の確認：
```bash
python3 ~/.claude-widget/claude_widget.py show
```

## アンインストール
```bash
curl -fsSL https://raw.githubusercontent.com/shikumake/claude-usage-widget/main/uninstall.sh | bash
```
Claude Code の設定は元に戻ります。iPhone の Scriptable にある「Claude Usage」は手動で削除してください。

## ライセンス
[MIT License](LICENSE)

作者：シクメイク（[X](https://x.com/shiku_make) / [note](https://note.com/shikumake)）
