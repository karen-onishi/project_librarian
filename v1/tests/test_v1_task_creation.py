import asyncio
import os
import sys
from google.adk.runners import InMemoryRunner
from google.genai import types 

# プロジェクトルートディレクトリをパスに追加
project_v1_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_v1_root)

# 環境設定 (インポート前に設定)
if not os.environ.get("PROJECT_ID"):
    os.environ["PROJECT_ID"] = "d001-000-chiel-dev"
if not os.environ.get("FIRESTORE_DB_NAME"):
    os.environ["FIRESTORE_DB_NAME"] = "(default)"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["LOG_LEVEL"] = "INFO"

from coordinator.agent import project_librarian_agent

async def main():
    APP_NAME = "v1_task_creation_test"
    TEST_USER = "oonishikaren@example.com"
    
    print("--- 🤖 プロジェクト図書館員 v1: タスク作成テスト 起動 ---")

    runner = InMemoryRunner(agent=project_librarian_agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(user_id=TEST_USER, app_name=APP_NAME)

    # テストシナリオ: タスク作成 -> 承認 -> サブタスク作成 -> 承認
    queries = [
        "プロジェクト 'エージェント開発支援' (ID: dummy_proj_123) にタスク '基本設計' を作成してください。期限は2026年3月末、担当は木下さん(naoya.kinoshita@enisias.jp)で。",
        "はい、それでお願いします", # タスク作成承認
        "今作った『基本設計』タスクの下に、サブタスク 'UIドラフト作成' を追加して。担当は私で、期限は3月15日です。",
        "はい、お願いします" # サブタスク作成承認
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
                        name = part.function_call.name
                        args = part.function_call.args
                        print(f"🔧 [TOOL CALL] {name}({args})")

if __name__ == "__main__":
    asyncio.run(main())
