from .state import AgentState
from .llm import get_llm
import os
import re

llm = get_llm()

# 必ず生成させる必須ファイル定義
REQUIRED_FILES = {
    "requirements.txt": "txt",
    "README.md": "md",
}

# 必須エンドポイント（メインファイルのコードに含まれているかチェック）
REQUIRED_ENDPOINTS = ["GET", "POST", "PUT", "DELETE"]

def extract_code_blocks(text: str) -> list[dict]:
    """
    Markdownのコードブロックを複数の形式に対応して抽出する

    対応形式：
    1. ```python:app/main.py  （理想形式）
    2. **app/main.py** の直後にある ```python ブロック
    3. # app/main.py の直後にある ```python ブロック
    """
    blocks = []

    # 形式1: ```言語:ファイルパス
    pattern1 = r"```(\w+):([^\n]+)\n(.*?)```"
    for lang, filepath, code in re.findall(pattern1, text, re.DOTALL):
        filepath = filepath.strip()
        filepath = re.sub(r'^\d+\.\s*', '', filepath)
        blocks.append({
            "language": lang.strip(),
            "filepath": filepath.strip(),
            "code": code.strip()
        })

    if blocks:
        return blocks

    # 形式2 & 3: ファイルパスラベルの直後のコードブロック
    pattern2 = r"(?:\*\*([^*\n]+\.\w+)\*\*|^#{1,3}\s+([^\n]+\.\w+))\s*\n```(\w*)\n(.*?)```"
    for m in re.finditer(pattern2, text, re.DOTALL | re.MULTILINE):
        filepath = (m.group(1) or m.group(2)).strip()
        filepath = re.sub(r'^\d+\.\s*', '', filepath)
        lang = m.group(3).strip() or "text"
        code = m.group(4).strip()
        if len(filepath) < 60 and ("." in filepath):
            blocks.append({
                "language": lang,
                "filepath": filepath,
                "code": code
            })

    return blocks

def write_files(blocks: list[dict], output_dir: str) -> list[str]:
    """抽出したコードブロックをファイルに書き出す"""
    written = []
    for block in blocks:
        full_path = os.path.join(output_dir, block["filepath"])
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(block["code"])
        written.append(full_path)
    return written

def check_missing(blocks: list[dict], output_dir: str) -> dict:
    """必須ファイルと必須エンドポイントの不足を検出する"""
    generated_paths = [b["filepath"] for b in blocks]
    all_code = "\n".join(b["code"] for b in blocks)

    # 必須ファイルのチェック
    missing_files = []
    for filename in REQUIRED_FILES:
        if not any(filename in p for p in generated_paths):
            missing_files.append(filename)

    # 必須エンドポイントのチェック
    missing_endpoints = []
    for method in REQUIRED_ENDPOINTS:
        # @app.get / @app.post / router.get 等のパターンで確認
        if not re.search(rf'@\w+\.{method.lower()}|"{method}"', all_code, re.IGNORECASE):
            missing_endpoints.append(method)

    return {
        "missing_files": missing_files,
        "missing_endpoints": missing_endpoints,
    }

def build_補完_prompt(proposal: str, blocks: list[dict], missing: dict) -> str:
    """不足分だけを再生成するプロンプトを構築する"""
    existing = "\n".join(f"- {b['filepath']}" for b in blocks)
    missing_files_text = "\n".join(f"- {f}" for f in missing["missing_files"])
    missing_ep_text = "\n".join(f"- {m}" for m in missing["missing_endpoints"])

    return f"""あなたは優秀なソフトウェアエンジニアです。
以下のファイルはすでに生成済みです：
{existing}

以下の不足しているファイル・機能を追加で実装してください。

[不足ファイル]
{missing_files_text if missing_files_text else "なし"}

[不足エンドポイント]
{missing_ep_text if missing_ep_text else "なし"}

[設計案（参考）]
{proposal}

[出力ルール]
- 各ファイルは必ず以下の形式で出力してください：
  ```言語:ファイルパス
  コード内容
  ```
- コメントは日本語で記述してください
- requirements.txt には使用するすべてのパッケージを1行1パッケージで記載してください
- README.md は以下の構成で簡潔に記述してください（長くしすぎない）：
  # プロジェクト名
  ## セットアップ
  （インストール・起動コマンドのみ）
  ## APIエンドポイント一覧
  （エンドポイントの箇条書きのみ）
- エラーハンドリングは HTTPException を使って適切に実装してください

【重要】日本語で回答してください。
/no_think
"""

def build_main_prompt(proposal: str) -> str:
    """メインのコード生成プロンプト"""
    return f"""あなたは優秀なソフトウェアエンジニアです。
以下の設計案をもとに、実際に動作するコードをすべて実装してください。

[設計案]
{proposal}

[必ず生成するファイル一覧]
以下のファイルをすべて生成してください。1つでも欠けてはいけません：
1. メインアプリケーションファイル（例：app/main.py）
2. データベース関連ファイル（例：app/db.py）
3. フロントエンドファイル（例：static/index.html）
4. requirements.txt（使用するすべてのパッケージを記載）
5. README.md（セットアップ手順・起動方法・APIエンドポイント一覧を記載）

[実装の必須要件]
- CRUDエンドポイントをすべて実装すること：
  - GET /items （一覧取得）
  - POST /items （作成）
  - PUT /items/{{id}} （更新）
  - DELETE /items/{{id}} （削除）
- すべてのエンドポイントに HTTPException を使ったエラーハンドリングを実装すること
- コメントは日本語で記述すること

[出力ルール]
各ファイルは必ず以下の形式で出力してください：
```言語:ファイルパス
コード内容
```

例：
```python:app/main.py
from fastapi import FastAPI
app = FastAPI()
```

【重要】日本語で回答してください。すべてのファイルを必ず出力してください。
/no_think
"""

def coder_agent(state: AgentState) -> AgentState:
    proposal = state.get("proposal", "")
    task = state.get("task", "")

    # 出力先ディレクトリ
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", task[:20])
    output_dir = os.path.join("output", safe_name)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs("proposals", exist_ok=True)

    # --- フェーズ1：メイン生成 ---
    print("💻 Coder がコードを生成中... (数分かかります)")
    response = llm.invoke(build_main_prompt(proposal))
    generated = response.content

    blocks = extract_code_blocks(generated)
    print(f"[DEBUG] 抽出されたコードブロック数: {len(blocks)}")
    for b in blocks:
        print(f"[DEBUG]   - {b['filepath']} ({b['language']})")

    # --- フェーズ2：不足チェック → 補完生成 ---
    missing = check_missing(blocks, output_dir)
    if missing["missing_files"] or missing["missing_endpoints"]:
        print(f"⚠️  不足を検出しました。補完生成します...")
        if missing["missing_files"]:
            print(f"   不足ファイル: {missing['missing_files']}")
        if missing["missing_endpoints"]:
            print(f"   不足エンドポイント: {missing['missing_endpoints']}")

        補完_response = llm.invoke(build_補完_prompt(proposal, blocks, missing))
        補完_blocks = extract_code_blocks(補完_response.content)
        print(f"[DEBUG] 補完で抽出されたブロック数: {len(補完_blocks)}")
        for b in 補完_blocks:
            print(f"[DEBUG]   - {b['filepath']} ({b['language']})")

        # 補完ブロックをマージ（既存と重複するパスは補完で上書き）
        existing_paths = {b["filepath"] for b in blocks}
        for b in 補完_blocks:
            if b["filepath"] in existing_paths:
                blocks = [x for x in blocks if x["filepath"] != b["filepath"]]
            blocks.append(b)

        generated += "\n\n---\n\n## 補完生成\n\n" + 補完_response.content
    else:
        print("✅ 必須ファイル・エンドポイントがすべて揃っています")

    # --- フェーズ3：ファイル書き出し ---
    written_files = write_files(blocks, output_dir)

    # 生成内容をMarkdownで保存
    with open("proposals/coder_output.md", "w", encoding="utf-8") as f:
        f.write(f"# Coder出力\n\n**タスク**: {task}\n\n---\n\n")
        f.write(generated)

    files_summary = "\n".join(written_files) if written_files else "（ファイルが抽出できませんでした）"

    return {
        **state,
        "generated_code": generated,
        "written_files": written_files,
        "output_dir": output_dir,
        "status": "code_generated",
        "messages": state.get("messages", []) + [
            {"role": "coder", "content": f"以下のファイルを生成しました：\n{files_summary}"}
        ]
    }