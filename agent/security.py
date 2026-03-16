"""
Securityエージェント
Coderが生成したコードに対して以下の2段階でセキュリティチェックを行う

フェーズ1: 静的解析ツール（bandit / eslint）による機械的チェック
フェーズ2: LLMによる解析結果の解釈・論理的な脆弱性の補完検出

検出結果はHIGH / MEDIUM / LOWに分類し、proposals/security_report.md に出力する
HIGHが1件でもある場合はstatusを "security_high" にしてHuman承認待ちにする
"""

import os
import re
import json
import subprocess
from .state import AgentState
from .llm import get_llm

llm = get_llm()

# 重大度レベル
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"


def run_bandit(output_dir: str) -> dict:
    """
    Pythonコードに対してbanditを実行する
    banditが未インストールの場合はスキップ
    """
    result = {"tool": "bandit", "available": False, "issues": [], "raw": ""}

    try:
        # banditが使えるか確認
        subprocess.run(
            ["bandit", "--version"],
            capture_output=True, check=True
        )
        result["available"] = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        result["raw"] = "banditがインストールされていません。`pip install bandit` で導入できます。"
        return result

    try:
        proc = subprocess.run(
            ["bandit", "-r", output_dir, "-f", "json", "-q"],
            capture_output=True, text=True, timeout=60
        )
        if proc.stdout:
            data = json.loads(proc.stdout)
            for issue in data.get("results", []):
                severity = issue.get("issue_severity", "LOW").upper()
                result["issues"].append({
                    "severity": severity,
                    "title": issue.get("issue_text", ""),
                    "file": issue.get("filename", ""),
                    "line": issue.get("line_number", 0),
                    "detail": issue.get("more_info", ""),
                    "source": "bandit"
                })
        result["raw"] = proc.stdout or proc.stderr
    except subprocess.TimeoutExpired:
        result["raw"] = "banditの実行がタイムアウトしました"
    except json.JSONDecodeError:
        result["raw"] = proc.stdout

    return result


def run_eslint(output_dir: str) -> dict:
    """
    JavaScript/TypeScriptコードに対してeslintを実行する
    eslintが未インストールの場合はスキップ
    """
    result = {"tool": "eslint", "available": False, "issues": [], "raw": ""}

    # JS/TSファイルが存在するか確認
    js_files = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith((".js", ".ts", ".jsx", ".tsx")):
                js_files.append(os.path.join(root, f))

    if not js_files:
        result["raw"] = "JS/TSファイルが見つかりませんでした（スキップ）"
        return result

    try:
        subprocess.run(
            ["npx", "eslint", "--version"],
            capture_output=True, check=True, timeout=10
        )
        result["available"] = True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        result["raw"] = "eslintが利用できません（スキップ）"
        return result

    try:
        proc = subprocess.run(
            ["npx", "eslint", "--format", "json"] + js_files,
            capture_output=True, text=True, timeout=60
        )
        if proc.stdout:
            data = json.loads(proc.stdout)
            for file_result in data:
                for msg in file_result.get("messages", []):
                    severity = SEVERITY_HIGH if msg.get("severity") == 2 else SEVERITY_LOW
                    result["issues"].append({
                        "severity": severity,
                        "title": msg.get("message", ""),
                        "file": file_result.get("filePath", ""),
                        "line": msg.get("line", 0),
                        "detail": msg.get("ruleId", ""),
                        "source": "eslint"
                    })
        result["raw"] = proc.stdout or proc.stderr
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        result["raw"] = str(e)

    return result


def collect_code(output_dir: str) -> str:
    """出力ディレクトリ内のコードを収集してテキストにまとめる"""
    code_text = ""
    extensions = (".py", ".js", ".ts", ".go", ".rs", ".html")
    for root, _, files in os.walk(output_dir):
        for fname in files:
            if fname.endswith(extensions):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read()
                    rel_path = os.path.relpath(fpath, output_dir)
                    code_text += f"\n\n### {rel_path}\n```\n{content}\n```"
                except Exception:
                    pass
    return code_text


def parse_llm_response(content: str) -> list[dict]:
    """
    LLMの出力をパースしてissueリストに変換する
    JSON形式で返ってこなかった場合も文章から重大度を推定して拾う
    """
    # コードブロック除去
    cleaned = re.sub(r"```(?:json)?\n?", "", content).strip("` \n")

    # まずJSONとして試みる
    try:
        issues = json.loads(cleaned)
        if isinstance(issues, list):
            return issues
    except json.JSONDecodeError:
        pass

    # JSON配列が文中に埋め込まれている場合を探す
    array_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if array_match:
        try:
            issues = json.loads(array_match.group())
            if isinstance(issues, list):
                return issues
        except json.JSONDecodeError:
            pass

    # JSONパース失敗 → 文章から問題を抽出する
    issues = []
    # 段落または番号付きリストで分割
    sections = re.split(r"\n#{1,3} |\n\d+\. ", cleaned)

    for section in sections:
        if not section.strip():
            continue

        # 重大度の推定
        text_lower = section.lower()
        if any(kw in text_lower for kw in ["高リスク", "high", "重大", "critical", "危険"]):
            severity = SEVERITY_HIGH
        elif any(kw in text_lower for kw in ["中リスク", "medium", "中程度", "注意"]):
            severity = SEVERITY_MEDIUM
        else:
            severity = SEVERITY_LOW

        # タイトルの抽出（最初の行）
        lines = section.strip().splitlines()
        title = lines[0].strip("# ").strip() if lines else "セキュリティ指摘"
        detail = "\n".join(lines[1:]).strip() if len(lines) > 1 else section.strip()

        # 短すぎるセクションはスキップ
        if len(title) < 5 or len(detail) < 10:
            continue

        # ファイル名の抽出
        file_match = re.search(r"`([^`]+\.(py|js|ts|html|go|rs))`", section)
        file_name = file_match.group(1) if file_match else ""

        issues.append({
            "severity": severity,
            "title": title[:80],
            "detail": detail[:500],
            "file": file_name,
            "source": "llm"
        })

    # 何も抽出できなかった場合は全文をMEDIUMとして返す
    if not issues and len(cleaned) > 20:
        issues.append({
            "severity": SEVERITY_MEDIUM,
            "title": "LLMセキュリティレビュー",
            "detail": cleaned[:800],
            "file": "",
            "source": "llm"
        })

    return issues


def llm_security_review(code_text: str, static_issues: list[dict]) -> list[dict]:
    """
    LLMによるセキュリティレビュー
    静的解析結果を渡して解釈・補完を行う
    """
    static_summary = ""
    if static_issues:
        static_summary = "\n[静的解析ツールの検出結果]\n"
        for issue in static_issues:
            static_summary += (
                f"- [{issue['severity']}] {issue['title']} "
                f"({issue['file']}:{issue['line']}) [{issue['source']}]\n"
            )
    else:
        static_summary = "\n[静的解析ツールの検出結果]\n検出なし\n"

    prompt = f"""あなたはセキュリティの専門家です。
以下のコードに対してセキュリティレビューを行ってください。
{static_summary}

[レビュー対象コード]
{code_text[:6000]}

以下の観点でチェックしてください：
- SQLインジェクションの可能性
- 認証・認可の抜け
- 機密情報のハードコード（パスワード・APIキーなど）
- 入力値のバリデーション不足
- XSS・CSRFの可能性（Webアプリの場合）
- DBコネクションの閉じ忘れ（close()の呼び忘れ）
- 静的解析ツールが検出した問題の解説と対処法

必ず以下のJSON配列形式のみで出力してください。前置き・説明文・コードブロックは不要です：
[
  {{
    "severity": "HIGH",
    "title": "問題のタイトル",
    "detail": "詳細な説明と対処法",
    "file": "該当ファイル名",
    "source": "llm"
  }}
]

severityはHIGH・MEDIUM・LOWのいずれかです。
問題がない場合は [] のみ出力してください。
/no_think
"""

    response = llm.invoke(prompt)
    content = response.content.strip()
    return parse_llm_response(content)


def classify_severity(issues: list[dict]) -> dict:
    """重大度ごとに問題を分類する"""
    classified = {SEVERITY_HIGH: [], SEVERITY_MEDIUM: [], SEVERITY_LOW: []}
    for issue in issues:
        severity = issue.get("severity", SEVERITY_LOW).upper()
        if severity not in classified:
            severity = SEVERITY_LOW
        classified[severity].append(issue)
    return classified


def generate_report(
    task: str,
    output_dir: str,
    classified: dict,
    tool_results: list[dict]
) -> str:
    """セキュリティレポートをMarkdown形式で生成する"""
    total = sum(len(v) for v in classified.values())
    high_count = len(classified[SEVERITY_HIGH])
    medium_count = len(classified[SEVERITY_MEDIUM])
    low_count = len(classified[SEVERITY_LOW])

    report = f"""# セキュリティレポート

**タスク**: {task}
**検査対象**: {output_dir}
**検出件数**: HIGH={high_count} / MEDIUM={medium_count} / LOW={low_count} / 合計={total}

---

"""
    # ツール実行結果サマリー
    report += "## 使用ツール\n\n"
    for tr in tool_results:
        status = "✅ 実行済み" if tr["available"] else "⚠️ スキップ"
        report += f"- **{tr['tool']}**: {status}\n"
    report += "\n---\n\n"

    # HIGH
    if classified[SEVERITY_HIGH]:
        report += "## 🔴 HIGH（要対応）\n\n"
        for i, issue in enumerate(classified[SEVERITY_HIGH], 1):
            report += f"### {i}. {issue['title']}\n"
            if issue.get("file"):
                report += f"- **ファイル**: {issue['file']}"
                if issue.get("line"):
                    report += f":{issue['line']}"
                report += "\n"
            report += f"- **検出元**: {issue.get('source', '不明')}\n"
            report += f"\n{issue.get('detail', '')}\n\n"

    # MEDIUM
    if classified[SEVERITY_MEDIUM]:
        report += "## 🟡 MEDIUM（推奨対応）\n\n"
        for i, issue in enumerate(classified[SEVERITY_MEDIUM], 1):
            report += f"### {i}. {issue['title']}\n"
            if issue.get("file"):
                report += f"- **ファイル**: {issue['file']}"
                if issue.get("line"):
                    report += f":{issue['line']}"
                report += "\n"
            report += f"- **検出元**: {issue.get('source', '不明')}\n"
            report += f"\n{issue.get('detail', '')}\n\n"

    # LOW
    if classified[SEVERITY_LOW]:
        report += "## 🟢 LOW（任意対応）\n\n"
        for i, issue in enumerate(classified[SEVERITY_LOW], 1):
            report += f"### {i}. {issue['title']}\n"
            if issue.get("file"):
                report += f"- **ファイル**: {issue['file']}"
                if issue.get("line"):
                    report += f":{issue['line']}"
                report += "\n"
            report += f"- **検出元**: {issue.get('source', '不明')}\n"
            report += f"\n{issue.get('detail', '')}\n\n"

    if total == 0:
        report += "## ✅ 問題は検出されませんでした\n"

    return report


def security_agent(state: AgentState) -> AgentState:
    output_dir = state.get("output_dir", "output")
    task = state.get("task", "")

    print("🔒 Security エージェントが検査を開始します...")

    # フェーズ1: 静的解析ツール
    print("  📋 フェーズ1: 静的解析ツールを実行中...")
    bandit_result = run_bandit(output_dir)
    eslint_result = run_eslint(output_dir)

    tool_results = [bandit_result, eslint_result]
    static_issues = bandit_result["issues"] + eslint_result["issues"]
    print(f"  静的解析: {len(static_issues)}件検出")

    # フェーズ2: LLMレビュー
    print("  🤖 フェーズ2: LLMによるセキュリティレビュー中...")
    code_text = collect_code(output_dir)
    llm_issues = llm_security_review(code_text, static_issues)
    print(f"  LLMレビュー: {len(llm_issues)}件検出")

    # 全問題をマージして重大度分類
    all_issues = static_issues + llm_issues
    classified = classify_severity(all_issues)

    high_count = len(classified[SEVERITY_HIGH])
    medium_count = len(classified[SEVERITY_MEDIUM])
    low_count = len(classified[SEVERITY_LOW])

    # レポート生成
    os.makedirs("proposals", exist_ok=True)
    report = generate_report(task, output_dir, classified, tool_results)
    report_path = "proposals/security_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n  結果: HIGH={high_count} / MEDIUM={medium_count} / LOW={low_count}")
    print(f"  📄 レポート保存: {report_path}")

    # HIGHがある場合はHuman承認待ち
    new_status = "security_high" if high_count > 0 else "security_passed"

    return {
        **state,
        "security_issues": all_issues,
        "security_classified": classified,
        "security_report_file": report_path,
        "status": new_status,
        "messages": state.get("messages", []) + [{
            "role": "security",
            "content": (
                f"セキュリティ検査完了: HIGH={high_count} / "
                f"MEDIUM={medium_count} / LOW={low_count}\n"
                f"レポート: {report_path}"
            )
        }]
    }