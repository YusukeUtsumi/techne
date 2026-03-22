import click
import yaml
from agent.orchestrator import build_graph, build_coder_graph
from agent.state import AgentState

graph = build_graph()
coder_graph = build_coder_graph()

@click.group()
def cli():
    pass

@cli.command()
@click.argument("task")
def run(task):
    """タスクを指示して設計案を生成する"""
    state: AgentState = {
        "task": task,
        "proposal": None,
        "reject_history": [],
        "section": None,
        "status": "pending",
        "messages": [],
        "last_proposal_file": None,
        "generated_code": None,
        "written_files": None,
        "output_dir": None,
        "security_issues": None,
        "security_classified": None,
        "security_report_file": None,
        "test_code": None,
        "test_results": None,
        "test_report_file": None,
    }

    click.echo("\n🏗️  Architect が設計案を生成中...\n")
    result = graph.invoke(state)

    filepath = result.get("last_proposal_file", "")
    click.echo("=" * 60)
    click.echo(result["proposal"])
    click.echo("=" * 60)
    if filepath:
        click.echo(f"\n📄 Markdownファイルに保存しました: {filepath}")
    click.echo("\n✅ python main.py approve  で承認 → Coderが実装を開始します")
    click.echo("❌ python main.py reject --reason \"理由\"  で差し戻し\n")

    with open(".agent_state.yaml", "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True)

@cli.command()
def approve():
    """設計案を承認してCoder→Securityを実行する"""
    with open(".agent_state.yaml", encoding="utf-8") as f:
        state = yaml.safe_load(f)

    state["status"] = "approved"

    click.echo("✅ 承認しました。Coderが実装を開始します...\n")
    click.echo("💻 コード生成中... (数分かかります)\n")

    try:
        result = coder_graph.invoke(state)
    except Exception as e:
        click.echo(f"\n❌ エラーが発生しました:\n{e}")
        import traceback
        traceback.print_exc()
        return

    # コード生成結果
    written = result.get("written_files", [])
    output_dir = result.get("output_dir", "output")

    click.echo("\n" + "=" * 60)
    if written:
        click.echo(f"✅ 以下のファイルを生成しました（{output_dir}/）:\n")
        for f in written:
            click.echo(f"   📝 {f}")
    else:
        click.echo("⚠️  ファイルの抽出に失敗しました。proposals/coder_output.md を確認してください。")
    click.echo(f"\n📄 コード全文: proposals/coder_output.md")
    click.echo("=" * 60)

    # セキュリティ結果の表示
    status = result.get("status", "")
    report_file = result.get("security_report_file", "")
    classified = result.get("security_classified") or {}
    high = len(classified.get("HIGH", []))
    medium = len(classified.get("MEDIUM", []))
    low = len(classified.get("LOW", []))

    click.echo("\n" + "=" * 60)
    if status == "security_high":
        click.echo(f"🔴 セキュリティ検査: HIGH={high} / MEDIUM={medium} / LOW={low}")
        click.echo(f"⚠️  HIGH問題が検出されました。レポートを確認してください。")
        if report_file:
            click.echo(f"📄 セキュリティレポート: {report_file}")
        click.echo("\n✅ python main.py security-approve  でHIGHを承認してTesterへ進む")
        click.echo("❌ python main.py security-reject    でCoderに修正依頼\n")
    else:
        click.echo(f"✅ セキュリティ検査パス: HIGH=0 / MEDIUM={medium} / LOW={low}")
        if report_file:
            click.echo(f"📄 セキュリティレポート: {report_file}")
    click.echo("=" * 60)

    # テスト結果の表示
    test_status = result.get("status", "")
    test_report = result.get("test_report_file", "")
    test_results = result.get("test_results") or {}

    if test_status in ("tests_passed", "tests_failed"):
        passed = test_results.get("passed", 0)
        failed = test_results.get("failed", 0)
        errors = test_results.get("errors", 0)
        click.echo("\n" + "=" * 60)
        if test_status == "tests_passed":
            click.echo(f"✅ テスト: PASS={passed} / FAIL={failed} / ERROR={errors}")
        else:
            click.echo(f"❌ テスト失敗: PASS={passed} / FAIL={failed} / ERROR={errors}")
            click.echo("⚠️  テストが失敗しています。レポートを確認してください。")
            click.echo('\n❌ python main.py test-reject --reason "修正理由"  でCoderに修正依頼\n')
        if test_report:
            click.echo(f"📄 テストレポート: {test_report}")
        click.echo("=" * 60)

    with open(".agent_state.yaml", "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True)

@cli.command()
@click.option("--reason", required=True, help="差し戻し理由")
@click.option("--section", default=None, help="部分修正対象セクション名")
def reject(reason, section):
    """設計案を差し戻す"""
    with open(".agent_state.yaml", encoding="utf-8") as f:
        state = yaml.safe_load(f)

    state["reject_history"] = state.get("reject_history", []) + [reason]
    state["section"] = section
    state["status"] = "rejected"

    click.echo(f"\n🔄 差し戻し理由を記録しました: {reason}")
    click.echo("🏗️  Architect が再設計中...\n")

    result = graph.invoke(state)

    filepath = result.get("last_proposal_file", "")
    click.echo("=" * 60)
    click.echo(result["proposal"])
    click.echo("=" * 60)
    if filepath:
        click.echo(f"\n📄 Markdownファイルに保存しました: {filepath}")
    click.echo("\n✅ python main.py approve  で承認")
    click.echo("❌ python main.py reject --reason \"理由\"  で差し戻し\n")

    with open(".agent_state.yaml", "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True)

@cli.command(name="security-approve")
def security_approve():
    """セキュリティのHIGH問題を承認してTesterへ進む"""
    with open(".agent_state.yaml", encoding="utf-8") as f:
        state = yaml.safe_load(f)

    state["status"] = "security_passed"  # Testerへのルーティングに合わせる
    click.echo("✅ セキュリティHIGHを承認しました。Testerを実行します...\n")

    from agent.orchestrator import build_tester_graph
    tester_graph = build_tester_graph()

    try:
        result = tester_graph.invoke(state)
    except Exception as e:
        click.echo(f"\n❌ エラーが発生しました:\n{e}")
        import traceback
        traceback.print_exc()
        return

    test_results = result.get("test_results") or {}
    passed = test_results.get("passed", 0)
    failed = test_results.get("failed", 0)
    errors = test_results.get("errors", 0)
    test_report = result.get("test_report_file", "")
    test_status = result.get("status", "")

    click.echo("\n" + "=" * 60)
    if test_status == "tests_passed":
        click.echo(f"✅ テスト: PASS={passed} / FAIL={failed} / ERROR={errors}")
    else:
        click.echo(f"❌ テスト失敗: PASS={passed} / FAIL={failed} / ERROR={errors}")
        click.echo('\n❌ python main.py test-reject --reason "修正理由"  でCoderに修正依頼\n')
    if test_report:
        click.echo(f"📄 テストレポート: {test_report}")
    click.echo("=" * 60)

    with open(".agent_state.yaml", "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True)

@cli.command(name="security-reject")
@click.option("--reason", required=True, help="修正依頼の理由")
def security_reject(reason):
    """セキュリティ問題をCoderに修正依頼する"""
    with open(".agent_state.yaml", encoding="utf-8") as f:
        state = yaml.safe_load(f)

    state["reject_history"] = state.get("reject_history", []) + [f"[セキュリティ修正] {reason}"]
    state["status"] = "approved"

    click.echo(f"\n🔄 修正依頼: {reason}")
    click.echo("💻 Coderが修正中...\n")

    result = coder_graph.invoke(state)

    written = result.get("written_files", [])
    click.echo("\n" + "=" * 60)
    if written:
        click.echo("✅ 修正されたファイル:")
        for f in written:
            click.echo(f"   📝 {f}")
    click.echo("=" * 60)

    status = result.get("status", "")
    classified = result.get("security_classified") or {}
    high = len(classified.get("HIGH", []))
    medium = len(classified.get("MEDIUM", []))
    low = len(classified.get("LOW", []))
    report_file = result.get("security_report_file", "")

    click.echo("\n" + "=" * 60)
    if status == "security_high":
        click.echo(f"🔴 まだHIGH問題があります: HIGH={high} / MEDIUM={medium} / LOW={low}")
        if report_file:
            click.echo(f"📄 レポート: {report_file}")
    else:
        click.echo(f"✅ セキュリティ検査パス: HIGH=0 / MEDIUM={medium} / LOW={low}")
    click.echo("=" * 60)

    with open(".agent_state.yaml", "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True)

@cli.command(name="test-reject")
@click.option("--reason", required=True, help="修正依頼の理由")
def test_reject(reason):
    """テスト失敗をCoderに修正依頼する"""
    with open(".agent_state.yaml", encoding="utf-8") as f:
        state = yaml.safe_load(f)

    state["reject_history"] = state.get("reject_history", []) + [f"[テスト修正] {reason}"]
    state["status"] = "approved"

    click.echo(f"\n🔄 修正依頼: {reason}")
    click.echo("💻 Coderが修正中...\n")

    result = coder_graph.invoke(state)

    written = result.get("written_files", [])
    click.echo("\n" + "=" * 60)
    if written:
        click.echo("✅ 修正されたファイル:")
        for f in written:
            click.echo(f"   📝 {f}")
    click.echo("=" * 60)

    test_results = result.get("test_results") or {}
    passed = test_results.get("passed", 0)
    failed = test_results.get("failed", 0)
    test_status = result.get("status", "")
    test_report = result.get("test_report_file", "")

    click.echo("\n" + "=" * 60)
    if test_status == "tests_passed":
        click.echo(f"✅ テスト: PASS={passed} / FAIL={failed}")
    else:
        click.echo(f"❌ まだテスト失敗があります: PASS={passed} / FAIL={failed}")
    if test_report:
        click.echo(f"📄 テストレポート: {test_report}")
    click.echo("=" * 60)

    with open(".agent_state.yaml", "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True)

@cli.command()
@click.option("--task", default="ToDoアプリをFastAPIで作りたい", help="テスト用タスク名")
def mock(task):
    """Architectをスキップしてダミー設計案でCoderをテストする"""
    dummy_proposal = """## 技術スタックの選定理由
- FastAPI：高速なAPI開発が可能で、自動ドキュメント生成が便利
- SQLite：シンプルなToDoアプリに十分な軽量DB
- HTML/CSS/JS：追加フレームワーク不要のシンプルなUI

## システム構成
FastAPIバックエンド + SQLiteデータベース + 静的フロントエンドの3層構成

## 主要コンポーネントの役割
- FastAPIサーバー：CRUD APIエンドポイントの提供
- SQLiteDB：タスクデータの永続化
- 静的フロントエンド：ユーザーインターフェース

## 懸念点・トレードオフ
- SQLiteは同時接続に弱いため、将来的にはPostgreSQLへの移行を検討
- 認証機能は含まれていないため、必要に応じてJWT認証を追加する
"""

    state: AgentState = {
        "task": task,
        "proposal": dummy_proposal,
        "reject_history": [],
        "section": None,
        "status": "approved",
        "messages": [{"role": "architect", "content": dummy_proposal}],
        "last_proposal_file": "proposals/mock_proposal.md",
        "generated_code": None,
        "written_files": None,
        "output_dir": None,
        "security_issues": None,
        "security_classified": None,
        "security_report_file": None,
        "test_code": None,
        "test_results": None,
        "test_report_file": None,
    }

    import os
    os.makedirs("proposals", exist_ok=True)
    with open("proposals/mock_proposal.md", "w", encoding="utf-8") as f:
        f.write(f"# ダミー設計案（mockモード）\n\n**タスク**: {task}\n\n---\n\n{dummy_proposal}")

    with open(".agent_state.yaml", "w", encoding="utf-8") as f:
        yaml.dump(state, f, allow_unicode=True)

    click.echo(f"🧪 mockモード：ダミー設計案を作成しました")
    click.echo(f"📄 proposals/mock_proposal.md に保存済み")
    click.echo(f"\n✅ python main.py approve  でCoder→Securityのテストを開始できます\n")

@cli.command()
def abort():
    """実行中のタスクを中断する"""
    import os
    if os.path.exists(".agent_state.yaml"):
        os.remove(".agent_state.yaml")
    click.echo("🛑 タスクを中断しました。")

@cli.command()
def status():
    """現在の実行状態を表示する"""
    import os
    if not os.path.exists(".agent_state.yaml"):
        click.echo("実行中のタスクはありません。")
        return
    with open(".agent_state.yaml", encoding="utf-8") as f:
        state = yaml.safe_load(f)
    click.echo(f"タスク    : {state.get('task')}")
    click.echo(f"ステータス: {state.get('status')}")
    history = state.get("reject_history", []) or []
    click.echo(f"差し戻し回数: {len(history)}")
    if history:
        for i, r in enumerate(history, 1):
            click.echo(f"  {i}回目: {r}")
    written = state.get("written_files")
    if written:
        click.echo(f"生成ファイル数: {len(written)}")
    classified = state.get("security_classified") or {}
    if classified:
        high = len(classified.get("HIGH", []))
        medium = len(classified.get("MEDIUM", []))
        low = len(classified.get("LOW", []))
        click.echo(f"セキュリティ: HIGH={high} / MEDIUM={medium} / LOW={low}")
    test_results = state.get("test_results") or {}
    if test_results:
        passed = test_results.get("passed", 0)
        failed = test_results.get("failed", 0)
        click.echo(f"テスト      : PASS={passed} / FAIL={failed}")
    if state.get("test_report_file"):
        click.echo(f"テストレポート: {state['test_report_file']}")

if __name__ == "__main__":
    cli()