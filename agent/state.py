from typing import TypedDict, Optional

class AgentState(TypedDict):
    task: str                          # ユーザーからの元タスク
    proposal: Optional[str]            # Architectの設計案
    reject_history: list[str]          # 差し戻し理由の履歴
    section: Optional[str]             # 部分修正対象セクション
    status: str                        # pending / awaiting_approval / approved /
                                        # code_generated / security_high /
                                        # security_passed / done
    messages: list[dict]               # エージェント間のメッセージログ
    last_proposal_file: Optional[str]  # 最後に保存した設計案ファイルパス
    generated_code: Optional[str]      # Coderが生成したコード全文
    written_files: Optional[list[str]] # 書き出したファイルパス一覧
    output_dir: Optional[str]          # コード出力先ディレクトリ
    security_issues: Optional[list]    # セキュリティ検出問題一覧
    security_classified: Optional[dict] # 重大度別に分類した問題
    security_report_file: Optional[str] # セキュリティレポートのパス
    # Tester
    test_code: Optional[str]           # 生成されたテストコード全文
    test_results: Optional[dict]       # テスト実行結果（passed/failed/errors/output）
    test_report_file: Optional[str]    # テストレポートのパス