import os
import sys
import argparse

# プロジェクトルートディレクトリをパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import A2aAgent
from vertexai.preview.reasoning_engines.templates.a2a import create_agent_card
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentProvider

# 自作モジュールのインポート
from coordinator.agent import project_librarian_agent
from coordinator.executor import ProjectLibrarianExecutor

PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = os.environ.get("LOCATION")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET_NAME")
REASONING_ENGINE_ID = os.environ.get("PROJECT_LIBRARIAN_REASONING_ENGINE_ID", "")
FIRESTORE_DB_NAME = os.environ.get("FIRESTORE_DB_NAME", "(default)")
if FIRESTORE_DB_NAME == "default":
    FIRESTORE_DB_NAME = "(default)"

ENV_VARS = {
    "PROJECT_ID": PROJECT_ID,
    "LOCATION": LOCATION,
    "FIRESTORE_DB_NAME": FIRESTORE_DB_NAME,
    "PROJECT_LIBRARIAN_REASONING_ENGINE_ID": REASONING_ENGINE_ID,
}
REQUIREMENTS = [
    "google-cloud-aiplatform[agent_engines,adk]",
    "google-adk==1.22.0",
    "a2a-sdk>=0.3.20",
    "google-cloud-firestore",
    "google-genai",
    "cloudpickle==3.1.2",
]
PACKAGES = ["agents", "common", "coordinator"]

# Vertex AI の初期化
vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
    staging_bucket=f"gs://{STAGING_BUCKET}-dev-onishi"
)

# エージェントカードの定義
def create_librarian_agent_card() -> AgentCard:
    skill = AgentSkill(
        description="Firestoreからプロジェクト情報を検索し、ユーザーに提案します。",
        examples=["プロジェクトについて教えて", "どんなプロジェクトがある？"],
        id="query_projects",
        # input_modes=[
        #     "text/plain"
        # ],
        input_modes=None, # 親(AgentCard)で定義するのでNone
        name="プロジェクト検索",
        # output_modes=[
        #     "text/plain",
        #     "text/markdown"
        # ],
        output_modes=None, # 親(AgentCard)で定義するのでNone
        security = None, # 認証不要
        tags=["projects"]
    )
    provider_info = AgentProvider(
        name="TenChan",
        organization="Big3",
        url="https://github.com/karen-onishi"
    )
    return AgentCard(
        additional_interfaces=None,
        capabilities = AgentCapabilities(),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "text/markdown"],
        description="プロジェクト情報の検索を行う図書館員エージェント",
        # description="プロジェクト情報の検索だけでなく、ユーザーの指示による情報の更新・登録も行う図書館員エージェント", # 将来的な機能はこれ
        documentation_url=None,
        icon_url=None,
        name="ProjectLibrarian",
        preferred_transport="HTTP+JSON",
        protocol_version="0.3.0",
        provider=provider_info,
        security = None,  # 認証不要
        security_schemes = None,  # 認証不要のため
        signatures = None,
        skills=[skill],
        supports_authenticated_extended_card = True, # TrueにしないとA2Aで動作しない
        url="https://github.com/karen-onishi/project_librarian", # Noneにできなかった
        version="0.0.1", # エージェント自身のバージョン
        
    )

# 4. A2aAgent の構成
def create_a2a_agent(resource_id=None):
    agent_card = create_librarian_agent_card()
    return A2aAgent(
        agent_card=agent_card,
        agent_executor_builder=lambda: ProjectLibrarianExecutor(
            agent=project_librarian_agent,
            resource_id=resource_id,
            project=PROJECT_ID,
            location=LOCATION
        ),
    )
# 5. デプロイ実行ロジック
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="既存のリソースを更新します")
    args = parser.parse_args()
    current_id = REASONING_ENGINE_ID if args.update else None
    a2a_agent = create_a2a_agent(resource_id=current_id)
    if args.update:
        if not REASONING_ENGINE_ID:
            print("エラー: 更新には PROJECT_LIBRARIAN_REASONING_ENGINE_ID の環境変数が必要です。")
            sys.exit(1)
        
        print(f"🔄 既存のリソース（ID: {REASONING_ENGINE_ID}）を更新中...")
        resource_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{REASONING_ENGINE_ID}"
        remote_engine = agent_engines.update(
            resource_name=resource_name,
            agent_engine=a2a_agent,
            requirements=REQUIREMENTS,
            extra_packages=PACKAGES,
            env_vars=ENV_VARS,
        )
    else:
        print("🚀 新規リソースを作成中...")
        remote_engine = agent_engines.create(
            agent_engine=a2a_agent,
            display_name="project_librarian",
            requirements=REQUIREMENTS,
            extra_packages=PACKAGES,
            env_vars=ENV_VARS,
        )