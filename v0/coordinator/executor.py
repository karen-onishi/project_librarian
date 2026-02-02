import os
from typing import Optional
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import VertexAiSessionService
from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import TextPart, TaskState
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message
from google.genai import types

class ProjectLibrarianExecutor(AgentExecutor):
    def __init__(self, agent: Agent, resource_id: Optional[str] = None, project: str = None, location: str = None):
        self.agent = agent
        self.resource_id = resource_id
        self.project = project
        self.location = location
        self.runner = None
        self.db = None
        self.mapping_collection = "a2a_session_mappings"
        self._app_id = resource_id or os.environ.get("PROJECT_LIBRARIAN_REASONING_ENGINE_ID") or "default-app"

    def _extract_user_id_from_context_id(self, context_id: str) -> str:
        """Extract user_id from A2A context_id.
        Context ID format: ADK/app_name/user_id/session_id
        """
        if not context_id:
            return ""
        try:
            parts = context_id.split("/")
            # ADK format usually has 4 parts
            if len(parts) >= 3 and parts[0] == "ADK":
                return parts[2]
        except:
            pass
        return ""

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # このエージェントではキャンセル処理は未実装としています
        raise NotImplementedError("Task cancellation is not supported")

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Runnerの初期化
        if not self.runner:
            # agent_engine_id を明示的に渡すことで、クラウド上のセッション管理を確実にします
            session_service = VertexAiSessionService(
                project=self.project, 
                location=self.location,
                agent_engine_id=self._app_id
            )
            self.runner = Runner(
                app_name=self._app_id,
                agent=self.agent,
                session_service=session_service,
            )

        # Firestore client の遅延初期化（Pickle対策）
        if self.db is None:
            from google.cloud import firestore
            db_name = os.environ.get("FIRESTORE_DB_NAME", "(default)")
            if db_name == "default":
                db_name = "(default)"
            self.db = firestore.AsyncClient(database=db_name)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task:
            await updater.submit()
        await updater.start_work()

        query = context.get_user_input()
        content = types.Content(role="user", parts=[types.Part(text=query)])
        
        # --- Ultra Robust user_id Extraction ---
        user_id = ""
        print(f"[ProjectLibrarian][DEBUG] context_id: {context.context_id}")
        print(f"[ProjectLibrarian][DEBUG] query: {query}")
        print(f"[ProjectLibrarian][DEBUG] message object: {repr(context.message)}")
        
        def extract_from_dict(d):
            if not isinstance(d, dict): return None
            return d.get("email_of_the_conversation_partner") or d.get("email") or d.get("user_id") or d.get("user")

        # 1. Standard Protocol/Metadata (Checked first)
        if getattr(context.message, "user_id", None):
            user_id = context.message.user_id
        if not user_id and hasattr(context.message, "metadata") and context.message.metadata:
            meta = context.message.metadata
            user_id = extract_from_dict(meta) if isinstance(meta, dict) else (getattr(meta, "user_id", None) or getattr(meta, "email", None))

        # 2. Deep Scanning of Parts (Handling Part(root=TextPart(...)))
        if not user_id and hasattr(context.message, "parts"):
            import json
            for i, part in enumerate(context.message.parts):
                # Try all possible text locations
                texts = []
                texts.append(getattr(part, "text", ""))
                if hasattr(part, "root"):
                    texts.append(getattr(part.root, "text", ""))
                    if isinstance(part.root, dict): texts.append(part.root.get("text", ""))
                
                for text in texts:
                    if not text or not isinstance(text, str): continue
                    if "{" in text:
                        try:
                            import re
                            # Extract all JSON-like chunks
                            for match in re.findall(r'\{.*?\}', text, re.DOTALL):
                                data = json.loads(match)
                                uid = extract_from_dict(data)
                                if uid:
                                    user_id = uid
                                    print(f"[ProjectLibrarian] Found user_id in part[{i}] JSON: {user_id}")
                                    break
                        except: pass
                    if user_id: break
                if user_id: break

        # 3. Last Resort: Regex scan of EVERYTHING (joined query + full message repr)
        if not user_id or user_id == "default_user":
            import re
            import json
            combined_search = query + " " + repr(context.message)
            
            # A. Try JSON-like structures
            for match in re.findall(r'\{.*?\}', combined_search, re.DOTALL):
                try:
                    j_str = match.replace("'", '"').replace("None", "null").replace("True", "true").replace("False", "false")
                    data = json.loads(j_str)
                    uid = extract_from_dict(data)
                    if uid:
                        user_id = uid
                        print(f"[ProjectLibrarian] Found user_id in combined regex (JSON): {user_id}")
                        break
                except: pass
            
            # B. Try plain text labels (email_of_the_conversation_partner: ...)
            if not user_id or user_id == "default_user":
                patterns = [
                    r"email_of_the_conversation_partner[:\s]+([^\s,{}]+)",
                    r"user_id[:\s]+([^\s,{}]+)",
                    r"email[:\s]+([^\s,{}]+)"
                ]
                for pattern in patterns:
                    match = re.search(pattern, combined_search)
                    if match:
                        user_id = match.group(1).strip('"\'')
                        print(f"[ProjectLibrarian] Found user_id in combined regex (Label): {user_id}")
                        break

        # 4. Final Fallback (Context ID)
        if not user_id:
            user_id = self._extract_user_id_from_context_id(context.context_id)
        
        user_id = user_id or "default_user"
        print(f"[ProjectLibrarian] Final selected user_id: {user_id}")
        # --- End Ultra Robust Extraction ---

        try:
            # context_id を本物の Vertex AI session_id に紐付ける（Vertex AIはカスタムID指定をサポートしていないため）
            session_id = None
            mapping_ref = self.db.collection(self.mapping_collection).document(context.context_id)
            doc = await mapping_ref.get()
            
            if doc.exists:
                session_id = doc.to_dict().get("session_id")
                print(f"[ProjectLibrarian] Mapping found: A2A context_id {context.context_id} -> Vertex session_id {session_id}")
            
            if not session_id:
                print(f"[ProjectLibrarian] No mapping found for context_id {context.context_id}, creating new Vertex session")
                session = await self.runner.session_service.create_session(
                    app_name=self._app_id,
                    user_id=user_id
                )
                session_id = session.id
                await mapping_ref.set({"session_id": session_id, "user_id": user_id})
                print(f"[ProjectLibrarian] Created mapping: context_id {context.context_id} -> session_id {session_id}")
            
            print(f"[ProjectLibrarian] Starting run_async with session_id: {session_id}, user_id: {user_id}")
    
            async for event in self.runner.run_async(
                session_id=session_id,
                user_id=user_id,
                new_message=content
            ):
                if event.content and event.content.parts:
                    # AIの返答から「テキスト」をすべてつなげて取得
                    all_text = "".join([p.text for p in event.content.parts if p.text])
                    
                    for part in event.content.parts:
                        # get_user_choiceがあったらA2Aの仕組みでユーザーに聞く
                        if part.function_call and part.function_call.name == "get_user_choice":
                            msg = part.function_call.args.get('message', '確認が必要です')
                            # AIがしゃべったテキストがあれば、それをメッセージの前に追加（Cortexで見えるようにする）
                            full_msg = f"{all_text}\n\n{msg}" if all_text else msg
                            await updater.add_artifact([TextPart(text=full_msg)], name="confirmation")
                            await updater.request_user_input()
                            return
                        
                        if part.text and event.is_final_response():
                            await updater.add_artifact([TextPart(text=part.text)], name="result")
                            await updater.complete()
                            return
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"[ProjectLibrarian] Error during execution: {error_detail}")
            await updater.update_status(TaskState.failed, message=new_agent_text_message(f"Error: {str(e)}"))