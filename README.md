# ローカルAIコーディングエージェント

OllamaによるローカルLLMを使い、設計・実装・セキュリティ検査・テストを自律的に実行するマルチエージェント型AIコーディングアシスタントです。外部APIへの依存なしにローカル環境で完結して動作します。

---

## 動作環境

| 項目 | 内容 |
|------|------|
| OS | macOS / Windows 11 |
| Python | 3.10 以上 |
| LLMランタイム | [Ollama](https://ollama.com/) |
| 推奨モデル | `qwen3:4b`（Q4_K_M量子化） |

### メモリ目安

| 構成 | 必要メモリ |
|------|----------|
| qwen3:4b（Q4_K_M） | 8GB以上推奨 |
| phi3:mini | 4GB以上 |

---

## セットアップ

### 1. Ollamaのインストールとモデルのダウンロード

```bash
# Ollamaをインストール（公式サイト: https://ollama.com/ ）

# モデルをダウンロード（Q4_K_M量子化版が自動で選択される）
ollama pull qwen3:4b

# 動作確認
ollama run qwen3:4b "こんにちは"
```

### 2. Pythonパッケージのインストール

```bash
pip install langgraph langchain-ollama langchain-core click pyyaml bandit pytest
```

### 3. プロジェクト構成

```
local-ai-agent/
├── agent/
│   ├── __init__.py
│   ├── architect.py      # 設計案を生成するエージェント
│   ├── coder.py          # コードを生成・書き出すエージェント
│   ├── security.py       # セキュリティ検査エージェント
│   ├── tester.py         # テストコード生成・実行エージェント
│   ├── orchestrator.py   # LangGraphによるグラフ制御
│   ├── state.py          # エージェント間共有ステートの型定義
│   └── llm.py            # LLMインスタンスの一元管理
├── tools/
│   └── __init__.py
├── output/               # Coderが生成したコードの出力先
├── proposals/            # 各エージェントの出力ログ
├── .agent_state.yaml     # 実行中のステート保存ファイル
├── agent.config.yaml     # 設定ファイル
└── main.py               # CLIエントリーポイント
```

---

## 設定

`agent.config.yaml` を編集してLLMやプロバイダーを切り替えられます。

```yaml
llm:
  provider: ollama        # ollama / gemini / openai
  model: qwen3:4b
  num_thread: 4           # Ollama専用：使用CPUスレッド数

project_root: ./
timeout_sec: 60
auto_commit: false

human_approval:
  after_architect: true
  after_security_high: true
  after_tests_pass: true

ollama_url: http://localhost:11434
```

### LLMプロバイダーの切り替え

```yaml
# Geminiに切り替える場合
llm:
  provider: gemini
  model: gemini-2.0-flash
  api_key: "your-google-api-key"
# pip install langchain-google-genai

# OpenAIに切り替える場合
llm:
  provider: openai
  model: gpt-4o
  api_key: "your-openai-api-key"
# pip install langchain-openai
```

---

## 使い方

### 基本フロー

```bash
# 1. タスクを指示してArchitectが設計案を生成
python main.py run "ToDoアプリをFastAPIで作りたい"

# 2a. 設計案を承認 → Coder → Security → Testerが順に実行される
python main.py approve

# 2b. 設計案を差し戻す（Architectが再設計）
python main.py reject --reason "差し戻し理由"
python main.py reject --reason "理由" --section "技術スタック"  # セクション指定も可
```

### セキュリティ検査後

```bash
# HIGHを無視してTesterへ進む
python main.py security-approve

# CoderにHIGH問題の修正を依頼
python main.py security-reject --reason "修正理由"
```

### テスト失敗後

```bash
# Coderにテスト失敗の修正を依頼
python main.py test-reject --reason "修正理由"
```

### その他のコマンド

```bash
# 現在の実行状態を確認
python main.py status

# 実行中のタスクをリセット
python main.py abort

# Architectをスキップしてダミー設計案でCoder以降をテスト（開発用）
python main.py mock
python main.py approve
```

---

## エージェントの処理フロー

```
python main.py run "タスク"
        ↓
  [Architect] 設計案を生成
        ↓
  Human: approve / reject（差し戻しは無制限）
        ↓ approve
  [Coder] コードを生成・ファイルに書き出す
    - フェーズ1: メイン生成
    - フェーズ2: 必須ファイル・エンドポイントの補完
    - フェーズ3: output/ フォルダへ書き出し
        ↓
  [Security] セキュリティ検査
    - フェーズ1: bandit / eslint による静的解析
    - フェーズ2: LLMによる補完レビュー
        ↓ HIGHなし              ↓ HIGH検出
  [Tester]               Human: security-approve / security-reject
    - フェーズ1: テストコード生成（LLM）
    - フェーズ2: pytest / jest で実行
    - フェーズ3: レポート出力
        ↓
  結果確認（proposals/test_report.md）
```

---

## 各エージェントの出力先

| エージェント | 出力ファイル |
|------------|------------|
| Architect | `proposals/proposal_r{N}.md` |
| Coder | `output/{タスク名}/`、`proposals/coder_output.md` |
| Security | `proposals/security_report.md` |
| Tester | `output/{タスク名}/tests/`、`proposals/tester_output.md`、`proposals/test_report.md` |

---

## 技術スタック

| カテゴリ | 採用技術 |
|--------|--------|
| エージェントフレームワーク | LangGraph |
| LLMランタイム | Ollama |
| CLIフレームワーク | Click |
| 設定管理 | PyYAML |
| 静的解析（Python） | bandit |
| 静的解析（JS/TS） | eslint（要別途インストール） |
| テスト（Python） | pytest |
| テスト（JS/TS） | jest |

---

## 開発上の注意点

### LLM速度について
- Apple Silicon（M1/M2）ではOllamaがMetalを自動で使用するため高速
- `num_thread` の設定はApple Silicon環境では効果が薄い
- プロンプト末尾の `/no_think` でQwen3の思考モードをオフにして高速化（必須）

### LangGraphのグラフ設計について
- `approve` コマンドは `build_coder_graph()`（Coderスタート）を使用
- `run` コマンドは `build_graph()`（Architectスタート）を使用
- `security-approve` コマンドは `build_tester_graph()`（Testerスタート）を使用
- 新コマンド追加時は「どのノードからスタートするか」に注意

### ステート管理について
- `.agent_state.yaml` に前回の状態が残るため、やり直す際は `python main.py abort` でリセット
- `status` フィールドの値でルーティングが決まるため、古い状態のままだと意図しない動作になる

### LLMの出力品質について
- モデルがJSONを返さない場合は `security.py` の `parse_llm_response()` でフォールバック処理
- コードブロックのファイルパス形式が毎回変わることがある（`coder.py` / `tester.py` で4パターン対応済み）
- テストコードの品質はモデルの能力に依存する。`phi3:mini` は軽量だがコード生成品質が低い

---

## ロードマップ

| 優先度 | 内容 |
|------|------|
| 🟡 中 | DEBUGログの削除（本番用クリーンアップ） |
| 🟡 中 | `--clean` オプション追加（outputフォルダをリセット） |
| 🟢 低 | Go / Rust の静的解析ツール対応（gosec / cargo clippy） |
| 🟢 低 | git commit の自動化（`auto_commit: true` 時） |

---
