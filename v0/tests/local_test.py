import asyncio
import os
import sys
from google.adk.runners import InMemoryRunner
from google.genai import types 

# プロジェクトルートディレクトリをパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from coordinator.agent import project_librarian_agent

async def main():
    # 環境設定
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    
    # アプリの名前を決めます
    APP_NAME = "test_app"
    
    print("--- 🤖 プロジェクト図書館員 起動 ---")

    # 【修正ポイント】Runnerにも APP_NAME を教えてあげます
    runner = InMemoryRunner(agent=project_librarian_agent, app_name=APP_NAME)
    
    # セッションを作ります（ここも同じ APP_NAME を使います）
    session = await runner.session_service.create_session(user_id="user_123", app_name=APP_NAME)

    # ユーザーの質問
    query = "今のプロジェクトについて教えて？"
    print(f"👤 ユーザー: {query}")
    
    content = types.Content(role="user", parts=[types.Part(text=query)])
    
    # エージェントを実行！
    async for event in runner.run_async(
        session_id=session.id, 
        user_id="user_123", 
        new_message=content
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"🤖 AI: {part.text}")
                
                # 承認待ち（質問）が発生した場合
                if part.function_call and part.function_call.name == "adk_request_confirmation":
                    print("\n❓ [システム] AIが確認を求めています。")

if __name__ == "__main__":
    asyncio.run(main())