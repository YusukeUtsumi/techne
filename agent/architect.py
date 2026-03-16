from .state import AgentState
from .llm import get_llm
import os

llm = get_llm()

def architect_agent(state: AgentState) -> AgentState:
    reject_history = state.get("reject_history", [])
    section = state.get("section")
    previous = state.get("proposal", "")

    # 差し戻し履歴を累積してプロンプトに付与
    history_text = ""
    if reject_history:
        history_text = "\n[差し戻し履歴]\n"
        for i, reason in enumerate(reject_history, 1):
            history_text += f"- {i}回目: {reason}\n"

    section_text = f"\n[修正対象セクション]\n{section}" if section else ""
    previous_text = f"\n[前回の設計案]\n{previous}" if previous else ""

    prompt = f"""あなたはソフトウェアアーキテクトです。
以下のタスクに対してシステム設計案をMarkdown形式で提案してください。
{history_text}{previous_text}{section_text}

[タスク]
{state['task']}

設計案には以下を含めてください：
- 技術スタックの選定理由
- システム構成
- 主要コンポーネントの役割
- 懸念点・トレードオフ

【重要】回答はすべて日本語で記述してください。英語は使わないでください。
/no_think
"""

    response = llm.invoke(prompt)
    proposal = response.content

    # proposals/ フォルダに自動保存
    os.makedirs("proposals", exist_ok=True)
    round_num = len(reject_history) + 1
    filename = f"proposals/proposal_r{round_num}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 設計案 (第{round_num}回)\n\n")
        f.write(f"**タスク**: {state['task']}\n\n")
        if reject_history:
            f.write("**差し戻し履歴**:\n")
            for i, reason in enumerate(reject_history, 1):
                f.write(f"- {i}回目: {reason}\n")
            f.write("\n---\n\n")
        f.write(proposal)

    return {
        **state,
        "proposal": proposal,
        "status": "awaiting_approval",
        "messages": state.get("messages", []) + [
            {"role": "architect", "content": proposal}
        ],
        "last_proposal_file": filename
    }