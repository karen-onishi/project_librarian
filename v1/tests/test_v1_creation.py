import asyncio
import os
import sys
from google.adk.runners import InMemoryRunner
from google.genai import types 

# プロジェクトルートディレクトリをパスに追加
# /Users/oonishikaren/Desktop/2026/chiel/agent/project_librarian/v1
project_v1_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_v1_root)

from coordinator.agent import project_librarian_agent

async def main():
    # 環境設定 (既存の環境変数があればそれを使う)
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    # デバッグ用にログレベルを上げると詳細が見えます
    os.environ["LOG_LEVEL"] = "DEBUG"
    
    APP_NAME = "v1_creation_test"
    TEST_USER = "oonishikaren@example.com"
    
    # 手動で渡す必要がある環境変数（必要に応じて）
    if not os.environ.get("PROJECT_ID"):
        os.environ["PROJECT_ID"] = "d001-000-chiel-dev"
    if not os.environ.get("FIRESTORE_DB_NAME"):
        os.environ["FIRESTORE_DB_NAME"] = "(default)"

    print("--- 🤖 プロジェクト図書館員 v1: 案件作成テスト 起動 ---")

    runner = InMemoryRunner(agent=project_librarian_agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(user_id=TEST_USER, app_name=APP_NAME)

    # ユーザーの質問
    queries = [
        "新しいプロジェクトを作ってほしいです。名前は『エージェント開発支援』、概要は『AIエージェントの開発を円滑に進めるためのライブラリ作成』です。担当は私（oonishikaren@example.com）でお願いします。",
        "はい、お願いします", # 承認
    ]
    
    for i, query in enumerate(queries):
        print(f"\n👤 ユーザー ({i+1}): {query}")
        content = types.Content(role="user", parts=[types.Part(text=query)])
        
        async for event in runner.run_async(
            session_id=session.id, 
            user_id=TEST_USER, 
            new_message=content
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(f"🤖 AI: {part.text}")
                    
                    if part.function_call:
                        # ツール名と引数を表示
                        args = part.function_call.args
                        print(f"🔧 [TOOL CALL] {part.function_call.name}({args})")

if __name__ == "__main__":
    asyncio.run(main())
