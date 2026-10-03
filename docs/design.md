# 設計: v1

調査結果は [research.md](research.md) を参照。

## 全体構成

```
~/.claude/projects/**.jsonl ─┐                       ┌─ GET /api/sessions?from&to
~/Library/.../claude-code-  ─┤   ingest (Python)     │  GET /api/sessions/{id}
  sessions/**/local_*.json   ├──▶ parse → normalize ──▶ SQLite ──▶ FastAPI ─┤  GET /api/usage
~/.claude/sessions/*.json   ─┤   （差分取り込み）       │                      └─ POST /api/ingest（読み直す）
~/.codex/sessions/**.jsonl  ─┤                         │                               │
~/.codex/session_index.jsonl┘                          └─ archive/（Claude 生 JSONL の退避）   ▼
                                                                                Vite + React（週カレンダー）
```

- データ: リポジトリ直下の `data/`（`history.db`、`archive/`、`logs/`）。`AGENT_HISTORY_HOME` で変更可。git 管理外
- 定期取り込み: launchd ユーザエージェント（1 時間ごと＋ログイン時）。詳細は README
- 時刻はすべて **UTC epoch ミリ秒** で保存し、表示時にローカル時刻へ変換する。

## 取り込み（ingest）

### 定期実行と健全性

- **間隔 1 時間**: Claude のクリーンアップは「最終更新から 30 日」のファイルが対象。どのセッションも最終書き込みから 1 時間以内に取り込まれるので余裕は約 720 倍。1 回 0.1 秒なので負荷は無視できる。
- **キャッチアップ**: `StartInterval` の取りこぼしはスリープ復帰後に 1 回へ集約され、`RunAtLoad` でログイン時にも走る。取り込み自体が冪等な全差分走査なので、間隔が空いても次の 1 回で追いつく。
- **失敗検知**: 実行ごとに `data/logs/ingest.jsonl` へ記録（1MB でローテート、1 世代保持）。失敗・部分失敗は macOS 通知。`agent-history status` は直近失敗または 24 時間成功なしで終了コード 1。
- **macOS のプライバシー保護**: バックグラウンドジョブが `~/Documents` などを覗くと許可ダイアログが出るため、プロジェクト名の推定（`.git` 探索）はこれらの配下ではファイルシステムに触れずパスから決める。

### パイプライン

1. **発見**: Claude の `projects/*/*.jsonl`（`subagents/` は v1 対象外）と Codex の `sessions/**/rollout-*.jsonl` を列挙する。
2. **差分判定**: `ingested_files(path, size, mtime_ns)` と比べ、変わったファイルだけを読む。
3. **パース**: ソースごとのパーサが 1 ファイル → `ParsedSession`（後述）を返す。パーサは純粋関数で、DB を知らない。
4. **保存**: セッション単位で `DELETE` → `INSERT`（冪等）。**元ファイルが消えても DB からは消さない**（Claude の 30 日削除対策）。
5. **退避**: Claude の JSONL は `data/archive/claude/<project>/<id>.jsonl` にコピーする（v2 の LLM 要約で生ログが必要になるため。約 100MB）。
6. **後処理**: 実行中セッションの判定。

### 正規化モデル（`ParsedSession`）

```
Session   id("claude:<uuid>" | "codex:<thread>"), source, native_id, parent_id, is_subagent,
          title, cwd, project, branch, repo_url, entrypoint,
          started_at, ended_at, cost_usd?, work_state?, work_detail?, needs_action?
Turn      key, seq, started_at, ended_at, state(completed|aborted|failed|open),
          prompt, prompt_kind(human|command|null), final_message,
          model, tokens{input, output, cache_read, cache_write, reasoning}
Segment   started_at, ended_at          … カレンダーの帯 1 本
Commit    turn_key, ts, sha?, branch?, kind(commit|push|pr)
FileChange turn_key, ts, path, added, removed
RateLimitSample ts, limit_id, window_minutes, used_percent, resets_at, plan_type   … Codex のみ
```

セッション単位の集計値（トークン合計・依頼件数・コミット数・変更ファイル数・モデル一覧）は DB 側でターン等から算出する（ビュー）。

### ターンの定義

| | ターンの開始 | ターンの終了 | 状態 |
|---|---|---|---|
| Claude | 人間の発言（下記ルール）| 次の人間の発言の直前の最後のレコード | `[Request interrupted by user]` → aborted、最後のアシスタント発言が `stop_reason=end_turn` → completed、それ以外 open |
| Codex | `task_started.turn_id` | `task_complete` / `turn_aborted` | complete → completed、aborted → aborted、どちらも無し → open |

**Claude の「人間の発言」判定**: `type=user` で `toolUseResult` なし、`isMeta` なし、`origin.kind` が無いか `human`。
`<command-name>/x</command-name>` は `/x` として `prompt_kind=command`。
`<ide_opened_file>`・`<system-reminder>` などのタグ部分は取り除く。`<task-notification>` はターンにせず、直前ターンの続きとして扱う。

### 帯（Segment）の作り方

セッション内の稼働時刻（Claude: user/assistant レコード、Codex: response_item/event_msg）を時系列に並べ、**30 分以上の空白で分割** する。
1 点だけの区間も残す（描画側で最小の高さを付ける）。閾値は設定値。

### トークン

- **Claude**: `assistant` は content block ごとに行が分かれ、同じ `message.id` で `usage` が重複するため、`message.id` で重複を除いて合計する。ターンへの割り当ては出現順。
- **Codex**: `token_count.info.total_token_usage` は **ルートセッション（親）全体の累計** で、サブエージェントでも親の累計がそのまま入る。
  そのため **`last_token_usage`（レスポンス 1 回分）を、累計値が変わったイベントだけ合計** する。ターンへの割り当ては直前の `task_started`。
  また Codex の `input_tokens` はキャッシュ分を含む（OpenAI 方式）ので、Claude に合わせて `input = input_tokens - cached_input_tokens`、`cache_read = cached_input_tokens` に正規化する。

### Codex の継承ターン（フォーク時のコピー）

フォークされたスレッドは親の履歴をコピーして持つことがあり、同じ `turn_id` が複数ファイルに現れる（実データでは全ターンの数 % 程度）。
コピー側のアイテムは子の `thread_id` に書き換えられているので `thread_id` では区別できないが、
`task_started.started_at` は元の開始時刻のまま残るため、**スレッド作成時刻より前に始まったターン = 継承ターン** としてパーサで捨てる
（ファイル間の突き合わせと過不足なく一致することを実データで確認済み）。継承ターン内のトークン・アイテム・稼働時刻もすべて除外する。

なお旧形式の `turn_id`（`rollout-4` など）はファイル内の連番で全体では一意でないため、ターンのキーは常にセッション ID と組で扱う。

### コミット・変更ファイル

- **Claude**: Bash の `toolUseResult.gitOperation`（`commit.sha/branch`、`push`、`pr`）と `pr-link`。変更ファイルは `Edit`/`Write` の `toolUseResult.filePath` と `structuredPatch` の `+`/`-` 行数。
- **Codex**: `CommandExecution` で `git commit` を含み `exit_code=0` のもの（SHA は出力の `[branch abc1234]` から取れたときだけ）。v2 で `git log` と突き合わせる。変更ファイルは `FileChange.changes` の `unified_diff`。

### 状態（完了判定）

詳細ペインのチェック項目に対応させるため、1 つの値にまとめずに部品を持つ。

| チェック | Claude | Codex |
|---|---|---|
| ターン終了 | 最終ターンが open でない | 同左 |
| 返事待ちなし | `postTurnSummary.needs_action` が空、かつ最後のツールが `AskUserQuestion` でない | 最終メッセージ以降に入力待ちがない（v1 は「ターン終了」と同じ） |
| コミット済み | コミット 1 件以上 | 同左（検出できた分のみ） |
| 作業内容 完了 | `postTurnSummary.status_category == completed`（デスクトップ起動のみ） | 取れない（v2 で LLM 判定） |
| 実行中 | `~/.claude/sessions/<pid>.json` に載っていて pid が生きている | 最終ターンが open かつ最終更新が 10 分以内 |

一覧のピル（完了 / やり残し / 途中で終了）は API で次のように決める:
実行中 → `running`、最終ターン aborted → `aborted`（途中で終了）、ターン終了かつ（作業完了 or 判定なし）→ `completed`、それ以外 → `incomplete`（やり残し）。

## SQLite スキーマ

```sql
sessions(id PK, source, native_id, parent_id, is_subagent, title, cwd, project, branch, repo_url, entrypoint,
         started_at, ended_at, cost_usd, work_state, work_detail, needs_action, is_running,
         source_path, ingested_at)
turns(session_id, key, seq, started_at, ended_at, state, prompt, prompt_kind, final_message, model,
      input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,
      PRIMARY KEY(session_id, key))
segments(session_id, started_at, ended_at)
commits(session_id, turn_key, ts, sha, branch, kind)
file_changes(session_id, turn_key, ts, path, added, removed)
rate_limits(ts, limit_id, window_minutes, used_percent, resets_at, plan_type,
            PRIMARY KEY(limit_id, window_minutes, ts))
ingested_files(path PK, source, size, mtime_ns, session_id)
```

## API（v1）

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/api/sessions?from=&to=&source=&project=` | 期間内に帯を持つセッション（帯・集計値・状態つき） |
| GET | `/api/sessions/{id}` | 詳細（ターン＝発言ログ、コミット、変更ファイル、チェック項目） |
| GET | `/api/usage` | 上部メーター: Codex のレート制限（5h / 7d の現在値と推移）、Claude のトークン量（直近 5h / 7d） |
| POST | `/api/ingest` | 読み直す |

## 画面（v1）

参考 UI に合わせ、取れるデータで作れる範囲に絞る。

- 上部: 使用量メーター（Codex 5h / 7d の % ゲージ＋スパークライン、Claude は直近 5h / 7d のトークン量）
- 2 段目: 一覧 / カレンダー切替、件数、状態ピル（完了・やり残し・途中で終了）、ソース絞り込み、読み直す
- 3 段目: 週ナビ（今週 / ◀ / ▶）、期間とセッション数、ズーム
- 4 段目: 色分け軸タブ（ソース / プロジェクト / モデル / 状態）＋件数つき凡例
- カレンダー: 月〜日 × 0〜24 時。帯は重なりを列分割で並べる。各列左端に 10 分刻みの発言量ヒートマップ。今日の列をハイライト
- 右ペイン: ヘッダ（ID・実行中バッジ・タイトル）、開始/最終/長さ/依頼件数、トークン、コスト、状態チェック、成果（コミット・変更ファイル、折りたたみ）、発言ログ（生のユーザ発言を時系列で）

v2: LLM による概要・発言の分類（相談/依頼/追加依頼）、Codex のコミット照合、サブエージェント展開、常駐化。

## テスト方針（TDD）

- パーサは実データの形をなぞった **小さな手書き JSONL フィクスチャ**（`tests/fixtures/`）で検証する。個人データはリポジトリに入れない。
- Store は一時ディレクトリの SQLite で、冪等性・元ファイル削除後も残ることを検証する。
- API は FastAPI の TestClient、フロントのロジック（帯の列割り当て・週計算・ヒートマップ集計）は Vitest。
