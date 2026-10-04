# agent-history

Claude Code と Codex のローカル履歴を取り込み、日・週・月のカレンダー上にセッションを並べて振り返るためのローカル Web アプリ。

- 取り込み元: `~/.claude/projects/**/*.jsonl`、`~/.codex/sessions/**/rollout-*.jsonl` ほか（詳細は [docs/research.md](docs/research.md)）
- 設計: [docs/design.md](docs/design.md)
- すべてローカルで完結する（外部送信なし。サーバは 127.0.0.1 のみで待ち受ける）

> **非公式ツールです。** Anthropic / OpenAI とは無関係で、Claude Code・Codex が手元に保存する**非公開の内部形式**を読んでいます。
> 各ツールの更新で形式が変わると取り込めなくなることがあります（調査した版は [docs/research.md](docs/research.md) 冒頭を参照）。

> Claude Code は既定で 30 日間更新のないセッションを自動削除します。`schedule install` で 1 時間ごとの取り込みを登録しておけば、
> 削除される前に DB と退避フォルダ（`data/archive/`）へ確実に残ります。

## 前提

| 必要なもの | バージョン | 備考 |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.11 以上 | Python 3.13 は `uv sync` が自動で用意する（`.python-version`） |
| Node.js | 20.19 以上 または 22.12 以上 | 画面のビルドにのみ使う（Vite 8 の要件） |
| Claude Code / Codex の履歴 | どちらか一方でも可 | 下の「読み込む場所」を参照。どちらも無ければ空の画面と案内が出る |

| OS | 取り込み・画面 | 定期取り込みの自動登録 | 失敗時の通知 |
|---|---|---|---|
| macOS | ○ | ○ launchd | ○ 通知センター |
| Windows 10 / 11 | ○ | ○ タスクスケジューラ | ○ トースト通知（ログにも必ず残る） |
| その他 | ○ | ×（案内を表示して終了。OS のスケジューラで `agent-history ingest --scheduled` を定期実行） | × |

不具合があれば Issue で教えてください。

### 読み込む場所

| 対象 | macOS | Windows | 変更する環境変数 |
|---|---|---|---|
| Claude Code のトランスクリプト | `~/.claude/projects/` | `%USERPROFILE%\.claude\projects\` | `CLAUDE_CONFIG_DIR`（Claude Code と同じ変数） |
| Claude デスクトップアプリのセッション情報（完了判定・タイトル） | macOS: `~/Library/Application Support/Claude/claude-code-sessions/` | `%APPDATA%\Claude\claude-code-sessions\` | `AGENT_HISTORY_CLAUDE_DESKTOP` |
| Codex の rollout | `~/.codex/sessions/` | `%USERPROFILE%\.codex\sessions\` | `CODEX_HOME`（Codex と同じ変数） |
| このツールのデータ | リポジトリ直下の `data/` | 同左 | `AGENT_HISTORY_HOME` |

デスクトップアプリの情報は無くても動く（完了判定が「?」になるだけ）。

## はじめかた

macOS（bash・zsh）:

```sh
git clone https://github.com/AbeTai/agent-history.git && cd agent-history
uv sync                                   # Python 環境を作る
(cd web && npm install && npm run build)  # 画面をビルド
uv run agent-history ingest               # 履歴を取り込む（初回でも数秒、以降は差分のみ 0.1 秒程度）
uv run agent-history serve                # http://127.0.0.1:8765 を開く（--port で変更可）
uv run agent-history schedule install     # 1 時間ごと＋ログイン時の定期取り込みを登録
```

Windows（PowerShell）:

```powershell
git clone https://github.com/AbeTai/agent-history.git; cd agent-history
uv sync
cd web; npm install; npm run build; cd ..
uv run agent-history ingest
uv run agent-history serve
uv run agent-history schedule install     # タスクスケジューラに登録（管理者権限は不要）
```

更新を取り込んだ（`git pull`）あとは `uv sync` と画面のビルドをやり直し、起動中の `serve` を再起動する
（API と画面の版がずれると表示がおかしくなる）。

## コマンド

```sh
uv run agent-history ingest              # 履歴を取り込む（見つからない履歴の場所も表示）
uv run agent-history serve [--port N]    # API と画面（web/dist）を 127.0.0.1 で起動
uv run agent-history status              # 取り込みの健全性（異常なら終了コード 1）
uv run agent-history schedule install    # 定期取り込みを登録（--interval 秒、--force）
uv run agent-history schedule uninstall  # 定期取り込みの登録解除

# 画面の開発（ホットリロード。/api は serve にプロキシ）
cd web && npm run dev
# serve のポートを変えたとき: AGENT_HISTORY_PORT=8766 npm run dev
#   （PowerShell: $env:AGENT_HISTORY_PORT=8766; npm run dev）
```

## 構成

| ディレクトリ | 内容 |
|---|---|
| `src/agent_history/` | 取り込み処理（パーサ・SQLite ストア）と FastAPI |
| `tests/` | pytest（手書きフィクスチャ） |
| `web/` | Vite + React + TypeScript の画面 |

### 画面

- 上部: Claude のトークン量（直近 5 時間 / 7 日、1 時間ごとの推移）と Codex のレート制限（5H / 7D の使用率と推移）
- 一覧 / カレンダー切替、状態ピル（完了・やり残し・途中で終了・実行中）での絞り込み、プロジェクト絞り込み、サブエージェント表示、読み直す
- 表示期間の切替（日 / 週 / 月）と移動（今日・今週・今月 / ◀ ▶ / キーボードの ← →）、日・週表示のズーム
- 色分け軸: プロジェクト / ツール / モデル / 完了か（上位 8 件まで色を割り当て、残りは「その他」）
- 日・週表示: 稼働区間ごとの帯（重なりは列分割）、各日の左端に 10 分刻みの依頼数ヒートマップ、現在時刻線
- 月表示: 各日のセッションを最初の活動時刻順に表示（前日から続くものは ↳）、日ごとの稼働時間、入りきらない分は「他 N 件」。日付を押すとその日の日表示へ
- コンテキストの圧縮（auto compact）: 日・週表示では帯の上に破線と ⟲ で位置を示し（手動は点線）、月表示は ⟲回数、
  一覧は「圧縮」列、詳細ペインは回数と発言ログ中の位置（圧縮前後のトークン数・所要時間）。「圧縮を表示」で表示を切り替えられる。
  Claude Code はログに自動 / 手動と前後のトークン数が記録される。Codex は種別が記録されないため、`/compact` の依頼の直後なら手動、
  それ以外は自動と推定し、トークン数は圧縮直前の使用量のみ
- 詳細ペイン（帯をクリック、Esc で閉じる）: 状態チェック、コミット・変更ファイル、最後の応答、サブエージェント、発言ログ

### 定期取り込み

`schedule install` は OS ごとに次の仕組みへ登録する。間隔は `--interval 秒`（既定 3600）。

| OS | 登録先 | スリープ・電源オフで飛んだ分 | 備考 |
|---|---|---|---|
| macOS | launchd ユーザエージェント `local.agent-history.ingest`（`~/Library/LaunchAgents/`） | 復帰後に 1 回へ集約して実行＋ログイン時に実行 | 出力は `data/logs/launchd.*.log` |
| Windows | タスクスケジューラのタスク `agent-history-ingest` | 「スケジュールされた時刻に開始できなかった場合すぐに実行」＋ログオン時に実行 | `pythonw.exe` で窓を出さずに実行。ログオン中のみ動く（パスワード保存不要） |

- 取り込みは毎回「前回以降の全差分」を拾うので、間が空いても次の 1 回で追いつく（Claude Code の自動削除は 30 日）。
- 実行ごとに `data/logs/ingest.jsonl` へ 1 行記録。失敗時（または一部ファイルが読めないとき）は OS の通知を出す。
  `status` は「直近が失敗」「最後の成功から 24 時間超」で NG（終了コード 1）になる。
- `.venv` を作り直したりリポジトリを移動したら `schedule install` をやり直すこと（登録内容に絶対パスが入るため）。
- 登録はユーザごとに 1 つ。別の場所に clone したリポジトリから `schedule install` すると、既存の登録を守るため拒否する
  （`status` にも「別のチェックアウトで登録済み」と出る）。置き換えるときは `--force`。
- `AGENT_HISTORY_HOME` などの環境変数を設定した状態で登録すると、その値も引き継ぐ（launchd は環境変数として、
  タスクスケジューラは環境変数を渡せないため `ingest --env KEY=VALUE` 引数として）。

### Windows での注意

- **文字コード**: 取り込むファイルはすべて UTF-8 として読み書きする（OS 既定の cp932 には依存しない）。
  コンソールへの出力は、リダイレクトやパイプ先が cp932 でも落ちないよう、表せない文字だけ `?` に置き換える
  （出力先の文字コードに合わせている）。
  通常のコンソール画面では日本語がそのまま表示される。日本語以外の Windows でパイプ・リダイレクトした場合はメッセージが
  `?` になるので、読みたいときは `$env:PYTHONUTF8=1` を設定して UTF-8 で受けること。
- **改行コード**: `.gitattributes` で LF に固定している。`core.autocrlf=true` でも問題ない。
- **実行中の判定**: Claude Code が動いているかの確認に、POSIX の `kill(pid, 0)` ではなく WinAPI（`OpenProcess`）を使う
  （Windows ではシグナル 0 が Ctrl+C の送信になるため）。
- 書き込み中でロックされたトランスクリプトの退避に失敗しても取り込み全体は止めず、次回に再試行する。

### データ

保存先はリポジトリ直下の `data/`（`AGENT_HISTORY_HOME` で変更可。リポジトリ外から動かした場合は
macOS は `~/.local/share/agent-history`、Windows は `%LOCALAPPDATA%\agent-history`）。
**git 管理には含めない**（`.gitignore` 済み）。

| パス | 内容 | 失ったら |
|---|---|---|
| `data/archive/` | Claude の生トランスクリプトの退避（約 100MB） | **元ファイルが消えた分は復元不可**。バックアップ対象 |
| `data/history.db` | 正規化済み SQLite（数 MB） | `ingest` で退避と元ファイルから再構築できる |
| `data/logs/` | 実行ログ | 影響なし |

作業内容の全文（発言・コード・ツール出力。トークン類が紛れ込むこともある）を含むため、GitHub に上げる場合も `data/` は絶対にコミットしないこと。
永続化は Time Machine / Windows のファイル履歴などのバックアップで担保する。

## テスト

```sh
uv run pytest                    # Python
uv run ruff check src tests      # lint
uv run mypy --platform win32     # 型チェック（darwin も同様）
cd web && npm test               # 画面のロジック（npm run build で型チェックも走る）
```

CI（GitHub Actions）では上記を macOS / Windows で実行し、Windows では実際のタスクスケジューラへの登録も確認する。

## ライセンス

[MIT](LICENSE)
