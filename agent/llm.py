"""
LLM初期化の一元管理モジュール
プロバイダーの切り替えはagent.config.yamlのllm.providerを変更するだけでOK

対応プロバイダー：
  - ollama  : ローカルLLM（デフォルト）
  - gemini  : Google Gemini
  - openai  : OpenAI GPT
"""

import yaml
import os

def load_config() -> dict:
    """agent.config.yamlを読み込む。なければデフォルト設定を返す"""
    config_path = "agent.config.yaml"
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def get_llm():
    """
    設定ファイルに基づいてLLMインスタンスを返す

    使い方：
        from agent.llm import get_llm
        llm = get_llm()
        response = llm.invoke("こんにちは")
    """
    config = load_config()
    llm_config = config.get("llm", {})

    provider = llm_config.get("provider", "ollama")
    model = llm_config.get("model", "qwen3:4b")

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model,
            num_thread=llm_config.get("num_thread", 4),
        )

    elif provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError(
                "Geminiを使うには以下を実行してください：\n"
                "pip install langchain-google-genai"
            )
        api_key = llm_config.get("api_key") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "Geminiのapi_keyが設定されていません。\n"
                "agent.config.yamlのllm.api_keyに設定するか、"
                "環境変数 GOOGLE_API_KEY を設定してください。"
            )
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
        )

    elif provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "OpenAIを使うには以下を実行してください：\n"
                "pip install langchain-openai"
            )
        api_key = llm_config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAIのapi_keyが設定されていません。\n"
                "agent.config.yamlのllm.api_keyに設定するか、"
                "環境変数 OPENAI_API_KEY を設定してください。"
            )
        return ChatOpenAI(
            model=model,
            api_key=api_key,
        )

    else:
        raise ValueError(
            f"未対応のプロバイダーです: {provider}\n"
            "対応プロバイダー: ollama / gemini / openai"
        )