# 調査メモ: Claude Code / Codex のローカル履歴

調査環境: macOS, Claude Code 2.1 系 / Codex CLI 0.155 系（2026 年 10 月時点）。バージョンが変わるとフォーマットも変わりうる。

## 1. Claude Code

### 保存場所

| パス | 内容 |
|---|---|
| `~/.claude/projects/<cwdをハイフン化>/<sessionId>.jsonl` | **本体**。1セッション = 1 JSONL（追記型） |
| `~/.claude/projects/<...>/<sessionId>/subagents/agent-*.jsonl` (+ `.meta.json`) | サブエージェントのトランスクリプト |
| `~/.claude/projects/<...>/<sessionId>/tool-results/` | 大きなツール出力の退避先 |
| `~/.claude/history.jsonl` | 入力プロンプト履歴（`display`, `timestamp`, `project`, `sessionId`）。バージョンによっては更新されなくなっている |
| `~/.claude/file-history/<sessionId>/<hash>@vN` | 編集前ファイルのバックアップ（チェックポイント用） |
| `~/.claude/sessions/<pid>.json` | **実行中**プロセスのメタ（cwd, name, status, entrypoint） |
| `~/Library/Application Support/Claude/claude-code-sessions/**/local_*.json` | デスクトップアプリ側のセッションメタ（`cliSessionId` で JSONL と紐付く） |

> ⚠️ **保存期間**: `cleanupPeriodDays`（既定 30 日）で古い JSONL は自動削除される。
> 実際、`history.jsonl` に記録が残っているのにトランスクリプト本体は削除済み、というセッションが確認できた。
> → このツールは「読むだけ」ではなく **自前ストアへ取り込んで蓄積** する必要がある（＋`cleanupPeriodDays` を伸ばす設定を推奨）。

### JSONL レコード種別

| type | 主なフィールド / 用途 |
|---|---|
| `assistant` | `message.{id,model,content[],usage,stop_reason}`, `timestamp`, `cwd`, `gitBranch`, `version`, `entrypoint`, `effort` |
| `user` | ユーザ発言 or `tool_result`。`toolUseResult` に構造化結果 |
| `attachment` | システムが差し込んだ文脈（`edited_text_file`, `queued_command` 等） |
| `ai-title` / `custom-title` | 自動生成タイトル / ユーザ命名タイトル（最後の値を採用） |
| `last-prompt` | 最新プロンプト |
| `system` | `api_error`, `compact_boundary`, `turn_duration`, `away_summary` 等 |
| `pr-link` | `prNumber`, `prUrl`, `prRepository` |
| `cost-state` | `totalCostUSD`, `totalLinesAdded/Removed`, `modelUsage{model:{tokens,costUSD}}` ※一部セッションのみ |
| `file-history-snapshot/delta` | 編集ファイルの追跡 |
| その他 | `mode`, `permission-mode`, `queue-operation`, `bridge-session`, `agent-name` |

`assistant` は **content block ごとに 1 行** に分割され、同じ `message.id` で `usage` が重複する → `message.id` で重複排除が必要。

### 1セッションから取れる情報

| 項目 | 取り方 | 確度 |
|---|---|---|
| 開始/終了時刻 | `user`/`assistant` の `timestamp` の min/max（UTC ISO8601） | ◎ |
| 実稼働区間 | タイムスタンプのギャップで分割（後述） | ○ |
| cwd / リポジトリ | `cwd`（途中で変わることあり） | ◎ |
| ブランチ | `gitBranch` | ◎ |
| モデル | `message.model`（`claude-opus-5`, `claude-sonnet-5`, `claude-opus-5-5` 等） | ◎ |
| トークン | `usage.{input,output,cache_read_input,cache_creation_input}_tokens` | ◎ |
| コスト | `cost-state.totalCostUSD`（あれば）／なければ usage × 単価表で算出 | △ |
| コミット | Bash の `toolUseResult.gitOperation.commit.{sha,branch}`（push / PR作成 / rebase も取れる） | ◎ |
| PR | `pr-link` | ◎ |
| 変更ファイル | `Edit`/`Write` の `toolUseResult.{filePath,structuredPatch}` | ◎ |
| 追加/削除行数 | `structuredPatch` から算出 | ○ |
| ユーザ発言 | `user` で `toolUseResult` なし・`isMeta` なし | ◎ |
| タイトル | `custom-title` > `ai-title` | ◎ |
| 使用ツール | `tool_use.name` 集計 | ◎ |
| 起動元 | `entrypoint`: `claude-desktop` / `cli` / `claude-vscode` / `sdk-cli` | ◎ |
| 完了判定 | デスクトップ側 `postTurnSummary.status_category`（`completed` 等）＋ `status_detail` | △ デスクトップ起動のみ |

## 2. Codex

### 保存場所

| パス | 内容 |
|---|---|
| `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<threadId>.jsonl` | **本体**（rollout）。1スレッド = 1 JSONL。長く使うと数百 MB になる |
| `~/.codex/state_5.sqlite` → `threads` テーブル | スレッド一覧のインデックス（title, cwd, model, tokens_used, git_branch, git_origin_url, created/updated_at, parent 関係） |
| `~/.codex/thread_history_1.sqlite` | `thread_turns`（turn ごとの status/started_at/completed_at/duration_ms）, `thread_items`（item_json） |
| `~/.codex/session_index.jsonl` | `id`, `thread_name`, `updated_at` |
| `~/.codex/logs_2.sqlite` | アプリログ（大きい。可視化には不要） |

SQLite は WAL 稼働中のため、読むときは **コピーしてから開く** か `immutable=1` で開く。

### rollout JSONL レコード種別

| type / payload.type | 用途 |
|---|---|
| `session_meta` | `id`, `cwd`, `originator`, `cli_version`, `git{commit_hash,branch,repository_url}`, `thread_source`(user/subagent), `parent_thread_id`, `agent_nickname` |
| `turn_context` | turn ごとの `model`, `effort`, `cwd`, `timezone`, `approval_policy`, `sandbox_policy` |
| `event_msg/task_started` / `task_complete` | **turn の開始・完了時刻**, `duration_ms`, `last_agent_message`（最終回答） |
| `event_msg/turn_aborted` | 中断 |
| `event_msg/token_count` | `total_token_usage`, `last_token_usage`, **`rate_limits`（5h枠/週枠の used_percent, plan_type）** |
| `token_usage_record` | response 単位の usage（turn / thread 累計つき） |
| `event_msg/item_completed` | `UserMessage`, `AgentMessage`, `CommandExecution`(command, cwd), `FileChange`(path → unified_diff), `McpToolCall`, `WebSearch`, `ContextCompaction` 等 |
| `response_item/*` | 生の API 入出力（reasoning は暗号化） |

### 1スレッドから取れる情報

| 項目 | 取り方 | 確度 |
|---|---|---|
| 開始/終了 | `threads.created_at/updated_at` または turn の min/max | ◎ |
| 実稼働区間 | **turn 単位の started_at/completed_at が明示的にある** | ◎ |
| cwd / リポジトリ | `cwd`, `git.repository_url` | ◎ |
| ブランチ / 開始時コミット | `git.branch`, `git.commit_hash` | ◎ |
| モデル / effort | `turn_context.model`, `effort` | ◎ |
| トークン | `token_count.total_token_usage`（input / cached / output / reasoning） | ◎ |
| コスト | 記録なし（サブスク利用、usage × 単価で推定のみ） | ✕〜△ |
| レート制限残量 | `rate_limits.primary/secondary.used_percent` | ◎（上部メーター向き） |
| コミット | 専用フィールドなし。`CommandExecution` の `git commit` を検出 or 後から `git log` と時間で突合 | △ |
| 変更ファイル | `FileChange.changes{path: {type, unified_diff}}` | ◎ |
| ユーザ発言 | `UserMessage.content[].text` | ◎（ChatGPT 参照の前置きが混ざる） |
| 最終回答 / 完了判定 | `task_complete.last_agent_message`, `thread_turns.status`(completed/failed/interrupted) | ○ |
| タイトル | `threads.title` / `session_index.thread_name` | ◎ |
| サブエージェント | `thread_spawn_edges`, `parent_thread_id`, `agent_nickname` | ◎ |

## 3. 共通 / 片方のみ

**共通で取れる（正規化スキーマの核）**
セッションID・タイトル・開始/終了・実稼働区間・cwd・ブランチ・モデル・入出力/キャッシュトークン・ユーザ発言・アシスタント最終メッセージ・実行コマンド・変更ファイル（＋diff）・サブエージェント親子関係・起動元（desktop/cli/vscode）

**Claude Code のみ**
- コミット SHA / push / PR 作成の構造化記録（`gitOperation`, `pr-link`）
- コスト（`cost-state`、一部のみ）・追加/削除行数
- 完了判定サマリ（デスクトップアプリの `postTurnSummary`）
- 30日で消える（要取り込み）

**Codex のみ**
- turn 単位の明示的な開始/完了/所要時間・ステータス（failed / interrupted）
- レート制限の使用率（5時間枠・週枠）
- reasoning トークン、effort、開始時の commit hash、リモート URL
- SQLite のインデックスがあり一覧取得が速い
- 自動削除は見当たらない

**どちらも無い → 生成が必要**
- 「セッション概要」「やりとりの要約」→ LLM で要約生成（キャッシュ）
- Codex のコミット数 → `git log --since/--until` を cwd のリポジトリで突合

## 4. データ量の目安

個人の利用（数か月、Claude Code と Codex を併用）で調べた規模感:

- セッション数は数十〜数百程度。Claude Code 側は 30 日の自動削除で直近分しか残らない。
- Codex はサブエージェントを多用するとスレッド数が一気に増える（1 つの親スレッドから 100 以上派生する例もあった）。
- 容量は Claude Code が数十〜100MB、Codex の rollout が数百 MB 程度。

所見:
- **1セッションが数日にまたがる**ことが多い（数日〜1 か月以上続くスレッドもある）。カレンダーの帯は「セッション全体」ではなく **稼働区間（turn / ギャップ分割）単位** で描く必要がある。
- Codex はサブエージェントが大量になりうる。既定では親セッションに畳み、展開で見せるのが良い。
- 規模は小さく、全件メモリ展開で問題ない。ただし Codex の JSONL は大きいので **差分取り込み（ファイルの mtime / byte offset 管理）** は欲しい。
