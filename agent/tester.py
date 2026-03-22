"""
Testerエージェント
Coderが生成したコードに対して以下の3フェーズでテストを行う

フェーズ1: テストコードの生成
  - Coderが生成したコードを読み込む
  - LLMにテストコードを生成させる
  - proposals/tester_output.md に保存

フェーズ2: テストの実行
  - 対象言語を判定してテストランナーを選択
    - Python → pytest
    - JS/TS  → jest / vitest
  - subprocess でテストを実行
  - 結果を解析してパス/フェイル件数を取得

フェーズ3: レポート生成
  - proposals/test_report.md に出力
  - 全テストパス → status = "tests_passed"
  - フェイルあり → status = "tests_failed"（Human承認待ち）
"""

import os
import re
import subprocess
from .state import AgentState
from .llm import get_llm

llm = get_llm()


# -------------------------------------------------------
# フェーズ1：テストコードの生成
# -------------------------------------------------------

def collect_code(output_dir: str) -> dict[str, str]:
    """
    出力ディレクトリ内のソースコードを収集する
    戻り値: {相対パス: コード内容}
    """
    extensions = (".py", ".js", ".ts", ".go", ".rs")
    files = {}
    for root, _, fnames in os.walk(output_dir):
        for fname in fnames:
            if fname.endswith(extensions):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read()
                    rel = os.path.relpath(fpath, output_dir)
                    files[rel] = content
                except Exception:
                    pass
    return files


def detect_language(files: dict[str, str]) -> str:
    """
    ファイル拡張子から主要言語を判定する
    戻り値: "python" / "javascript" / "typescript" / "unknown"
    """
    counts = {"python": 0, "javascript": 0, "typescript": 0}
    for path in files:
        if path.endswith(".py"):
            counts["python"] += 1
        elif path.endswith(".ts") or path.endswith(".tsx"):
            counts["typescript"] += 1
        elif path.endswith(".js") or path.endswith(".jsx"):
            counts["javascript"] += 1
    return max(counts, key=lambda k: counts[k]) if any(counts.values()) else "unknown"


def build_test_prompt(files: dict[str, str], language: str) -> str:
    """テストコード生成プロンプトを構築する"""
    code_text = ""
    for path, content in files.items():
        code_text += f"\n### {path}\n```\n{content}\n```\n"

    if language == "python":
        framework = "pytest"
        test_file = "tests/test_main.py"
        example = (
            "必ず以下の形式で出力してください：\n"
            "```python:tests/test_main.py\n"
            "import pytest\n"
            "from fastapi.testclient import TestClient\n"
            "from app.main import app\n\n"
            "client = TestClient(app)\n\n"
            "def test_get_items():\n"
            "    response = client.get('/items')\n"
            "    assert response.status_code == 200\n"
            "```\n\n"
            "ファイルパスを必ず含めてください。```python だけではなく ```python:tests/test_main.py の形式で出力すること。"
        )
    else:
        framework = "jest"
        test_file = "tests/main.test.js"
        example = (
            "```javascript:tests/main.test.js\n"
            "const request = require('supertest');\n"
            "const app = require('../app');\n\n"
            "test('GET /items returns 200', async () => {\n"
            "    const res = await request(app).get('/items');\n"
            "    expect(res.statusCode).toBe(200);\n"
            "});\n"
            "```"
        )

    return f"""あなたは優秀なソフトウェアエンジニアです。
以下のコードに対して {framework} を使ったテストコードを生成してください。

[対象コード]
{code_text[:5000]}

[テスト要件]
- 各エンドポイントの正常系テストを実装すること（GET/POST/PUT/DELETE）
- ステータスコードとレスポンス形式を検証すること
- テストは独立して実行できること（テスト間で依存しない）
- テストデータはテスト内で完結させること

[出力形式]
以下の形式で出力してください：
{example}

【重要】日本語でコメントを記述してください。
/no_think
"""


def extract_test_blocks(text: str) -> list[dict]:
    """テストコードブロックを抽出する（coder.pyと同じロジック）"""
    blocks = []

    # 形式1: ```言語:ファイルパス
    pattern1 = r"```(\w+):([^\n]+)\n(.*?)```"
    for lang, filepath, code in re.findall(pattern1, text, re.DOTALL):
        blocks.append({
            "language": lang.strip(),
            "filepath": filepath.strip(),
            "code": code.strip()
        })

    if blocks:
        return blocks

    # 形式2: **ファイルパス** の直後のコードブロック
    pattern2 = r"(?:\*\*([^*\n]+\.\w+)\*\*|^#{1,3}\s+([^\n]+\.\w+))\s*\n```(\w*)\n(.*?)```"
    for m in re.finditer(pattern2, text, re.DOTALL | re.MULTILINE):
        filepath = (m.group(1) or m.group(2)).strip()
        lang = m.group(3).strip() or "text"
        code = m.group(4).strip()
        if len(filepath) < 60 and ("." in filepath):
            blocks.append({
                "language": lang,
                "filepath": filepath,
                "code": code
            })

    return blocks


def write_test_files(blocks: list[dict], base_dir: str) -> list[str]:
    """テストコードをファイルに書き出す"""
    written = []
    for block in blocks:
        full_path = os.path.join(base_dir, block["filepath"])
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(block["code"])
        written.append(full_path)
        print(f"  📝 テストファイル生成: {full_path}")
    return written


# -------------------------------------------------------
# フェーズ2：テストの実行
# -------------------------------------------------------

def run_pytest(test_dir: str, output_dir: str) -> dict:
    """
    pytest を実行する
    戻り値: {passed, failed, errors, output, success}
    """
    result = {
        "runner": "pytest",
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "output": "",
        "success": False,
    }

    # pytest がインストールされているか確認
    try:
        subprocess.run(
            ["python", "-m", "pytest", "--version"],
            capture_output=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        result["output"] = "pytest がインストールされていません。`pip install pytest` で導入できます。"
        return result

    try:
        proc = subprocess.run(
            [
                "python", "-m", "pytest",
                test_dir,
                "-v",
                "--tb=short",
                f"--rootdir={output_dir}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=output_dir,
        )
        output = proc.stdout + proc.stderr
        result["output"] = output

        # 結果をパース: "X passed, Y failed" 形式
        passed_match = re.search(r"(\d+) passed", output)
        failed_match = re.search(r"(\d+) failed", output)
        error_match = re.search(r"(\d+) error", output)

        result["passed"] = int(passed_match.group(1)) if passed_match else 0
        result["failed"] = int(failed_match.group(1)) if failed_match else 0
        result["errors"] = int(error_match.group(1)) if error_match else 0
        result["success"] = proc.returncode == 0

    except subprocess.TimeoutExpired:
        result["output"] = "テストの実行がタイムアウトしました（120秒）"
    except Exception as e:
        result["output"] = f"テスト実行中にエラーが発生しました: {e}"

    return result


def run_jest(test_dir: str, output_dir: str) -> dict:
    """
    jest を実行する
    戻り値: {passed, failed, errors, output, success}
    """
    result = {
        "runner": "jest",
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "output": "",
        "success": False,
    }

    try:
        subprocess.run(
            ["npx", "jest", "--version"],
            capture_output=True, check=True, timeout=10
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        result["output"] = "jest が利用できません（スキップ）"
        return result

    try:
        proc = subprocess.run(
            ["npx", "jest", "--no-coverage", "--verbose"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=output_dir,
        )
        output = proc.stdout + proc.stderr
        result["output"] = output

        passed_match = re.search(r"(\d+) passed", output)
        failed_match = re.search(r"(\d+) failed", output)

        result["passed"] = int(passed_match.group(1)) if passed_match else 0
        result["failed"] = int(failed_match.group(1)) if failed_match else 0
        result["success"] = proc.returncode == 0

    except subprocess.TimeoutExpired:
        result["output"] = "テストの実行がタイムアウトしました（120秒）"
    except Exception as e:
        result["output"] = f"テスト実行中にエラーが発生しました: {e}"

    return result


def run_tests(language: str, test_dir: str, output_dir: str) -> dict:
    """言語に応じたテストランナーを選択して実行する"""
    if language == "python":
        return run_pytest(test_dir, output_dir)
    elif language in ("javascript", "typescript"):
        return run_jest(test_dir, output_dir)
    else:
        return {
            "runner": "unknown",
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "output": f"未対応の言語です: {language}",
            "success": False,
        }


# -------------------------------------------------------
# フェーズ3：レポート生成
# -------------------------------------------------------

def generate_test_report(
    task: str,
    language: str,
    test_result: dict,
    test_files: list[str],
) -> str:
    """テストレポートをMarkdown形式で生成する"""
    passed = test_result["passed"]
    failed = test_result["failed"]
    errors = test_result["errors"]
    total = passed + failed + errors
    runner = test_result["runner"]
    success = test_result["success"]

    status_icon = "✅" if success else "❌"
    status_text = "全テストパス" if success else "テスト失敗あり"

    report = f"""# テストレポート

**タスク**: {task}
**言語**: {language}
**テストランナー**: {runner}
**結果**: {status_icon} {status_text}
**件数**: PASS={passed} / FAIL={failed} / ERROR={errors} / 合計={total}

---

## 生成されたテストファイル

"""
    for tf in test_files:
        report += f"- `{tf}`\n"

    report += f"""
---

## テスト実行ログ

```
{test_result['output'][:3000]}
```
"""

    if not success:
        report += """
---

## 対処方法

テストが失敗しています。以下を確認してください：

1. **インポートエラー**: アプリケーションの依存パッケージがインストールされているか
2. **エンドポイントの差異**: テストが想定しているURLやレスポンス形式とコードが一致しているか
3. **DBの初期化**: テスト実行前にDBが正しく初期化されているか

`python main.py security-reject --reason "テスト失敗の内容"` でCoderに修正依頼できます。
"""

    return report


# -------------------------------------------------------
# メインのエージェント関数
# -------------------------------------------------------

def tester_agent(state: AgentState) -> AgentState:
    output_dir = state.get("output_dir", "output")
    task = state.get("task", "")

    print("🧪 Tester エージェントがテストを開始します...")
    os.makedirs("proposals", exist_ok=True)

    # ソースコードを収集
    source_files = collect_code(output_dir)
    if not source_files:
        print("  ⚠️ テスト対象のソースファイルが見つかりませんでした")
        return {
            **state,
            "test_code": None,
            "test_results": {"runner": "none", "passed": 0, "failed": 0, "errors": 0,
                             "output": "テスト対象ファイルなし", "success": False},
            "test_report_file": None,
            "status": "tests_failed",
        }

    language = detect_language(source_files)
    print(f"  🔍 検出言語: {language} ({len(source_files)}ファイル)")

    # -------------------------------------------------------
    # フェーズ1：テストコードの生成
    # -------------------------------------------------------
    print("  📝 フェーズ1: テストコードを生成中...")
    prompt = build_test_prompt(source_files, language)
    response = llm.invoke(prompt)
    test_code_raw = response.content

    # テストコードをファイルに書き出す
    test_blocks = extract_test_blocks(test_code_raw)
    print(f"  抽出されたテストブロック数: {len(test_blocks)}")

    test_dir = os.path.join(output_dir, "tests")
    os.makedirs(test_dir, exist_ok=True)

    written_test_files = write_test_files(test_blocks, output_dir)

    # テストコード全文をMarkdownで保存
    with open("proposals/tester_output.md", "w", encoding="utf-8") as f:
        f.write(f"# Tester出力\n\n**タスク**: {task}\n\n---\n\n")
        f.write(test_code_raw)

    # -------------------------------------------------------
    # フェーズ2：テストの実行
    # -------------------------------------------------------
    print(f"  🚀 フェーズ2: テストを実行中 (runner: {'pytest' if language == 'python' else 'jest'})...")
    test_result = run_tests(language, test_dir, output_dir)

    passed = test_result["passed"]
    failed = test_result["failed"]
    print(f"  結果: PASS={passed} / FAIL={failed} / ERROR={test_result['errors']}")

    # -------------------------------------------------------
    # フェーズ3：レポート生成
    # -------------------------------------------------------
    print("  📄 フェーズ3: レポートを生成中...")
    report = generate_test_report(task, language, test_result, written_test_files)
    report_path = "proposals/test_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  レポート保存: {report_path}")

    # ステータス判定
    new_status = "tests_passed" if test_result["success"] else "tests_failed"

    return {
        **state,
        "test_code": test_code_raw,
        "test_results": test_result,
        "test_report_file": report_path,
        "status": new_status,
        "messages": state.get("messages", []) + [{
            "role": "tester",
            "content": (
                f"テスト完了: PASS={passed} / FAIL={failed}\n"
                f"レポート: {report_path}"
            )
        }]
    }