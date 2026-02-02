"""Simple Firestore tools for ADK agents."""

from google.cloud import firestore
from typing import Any, Optional, List, Dict
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo
import uuid

from common.const import PROJECT_ID, FIRESTORE_DATABASE, logger
from common.utils import convert_utc_to_jst

# グローバルなFirestoreクライアント（再利用可能でスレッドセーフ）
logger.debug(
    f"🔧 Initializing Firestore client (project={PROJECT_ID}, database={FIRESTORE_DATABASE})"
)
_db_client = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DATABASE)
logger.debug(f"✅ Firestore client initialized successfully (id: {id(_db_client)})")


def _clean_firestore_data(data: Any) -> Any:
    """
    FirestoreのデータからJSON化できないオブジェクトを除去・変換する
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            cleaned_value = _clean_firestore_data(value)
            if cleaned_value is not None:  # Noneでない値のみ追加
                cleaned[key] = cleaned_value
        return cleaned
    elif isinstance(data, list):
        return [_clean_firestore_data(item) for item in data if _clean_firestore_data(item) is not None]
    elif hasattr(data, '_document_path'):  # DocumentReference
        # DocumentReferenceの場合はパスを文字列として返す
        return str(data.path) if hasattr(data, 'path') else str(data)
    elif hasattr(data, 'timestamp'):  # Timestamp
        # Timestampの場合はISO文字列に変換
        return data.isoformat() if hasattr(data, 'isoformat') else str(data)
    elif isinstance(data, (str, int, float, bool)) or data is None:
        return data
    else:
        # その他のオブジェクトは文字列化
        try:
            # JSON化を試行
            import json
            json.dumps(data)
            return data
        except (TypeError, ValueError):
            return str(data)


def _get_subtasks_recursively(
    task_doc_ref, db, level=1, max_level=3
) -> list[dict[str, Any]]:
    """
    タスクドキュメントからサブタスクを再帰的に取得する

    Args:
        task_doc_ref (firestore.DocumentReference): 親タスクのFirestoreドキュメント参照
        db (firestore.Client): Firestoreクライアント
        level (int, optional): 現在のネストレベル（直接のサブタスクは1から開始）. Defaults to 1.
        max_level (int, optional): 無限再帰を防ぐための最大ネストレベル. Defaults to 3.

    Returns:
        list[dict[str, Any]]: 階層情報を含むサブタスク辞書のリスト
    """
    if level > max_level:
        print(f"   ⚠️  Max nesting level ({max_level}) reached, stopping recursion")
        return []

    try:
        subtasks = []
        subtasks_collection = task_doc_ref.collection("subTasks")
        subtask_docs = subtasks_collection.stream()

        for subtask_doc in subtask_docs:
            if subtask_doc.exists:
                subtask_dict = subtask_doc.to_dict()
                subtask_dict["taskId"] = subtask_doc.id
                subtask_dict["taskPath"] = subtask_doc.reference.path
                subtask_dict["isSubTask"] = True
                subtask_dict["parentTaskPath"] = task_doc_ref.path
                subtask_dict["nestingLevel"] = level

                print(
                    f"   {'  ' * level}📋 Found subtask: {subtask_dict.get('title', 'No title')} (level {level})"
                )

                subtasks.append(subtask_dict)

                # Recursively get sub-subtasks
                nested_subtasks = _get_subtasks_recursively(
                    subtask_doc.reference, db, level + 1, max_level
                )
                subtasks.extend(nested_subtasks)

        return subtasks

    except Exception as e:
        print(f"   ❌ Error getting subtasks at level {level}: {str(e)}")
        return []


def _get_user_context(
    email_of_the_conversation_partner: str,
) -> dict[str, Any]:
    """
    Firestoreからユーザーコンテキストを取得する

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        dict[str, Any]: ユーザーコンテキストを含む辞書、見つからない場合は空の辞書
    """
    try:
        db = _db_client
        collection_ref = (
            db.collection("users")
            .document(email_of_the_conversation_partner)
            .collection("userContexts")
        )
        docs = (
            collection_ref.order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )

        for doc in docs:
            logger.debug(doc.to_dict())
            if doc.exists:
                return doc.to_dict()

        return {}

    except Exception as e:
        print(f"Error retrieving user context: {str(e)}")
        return {"error": f"Failed to retrieve user context: {str(e)}"}


def _get_project_context(
    email_of_the_conversation_partner: str,
) -> dict[str, Any]:
    """
    Firestoreからプロジェクトコンテキストを取得する

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        dict[str, Any]: プロジェクトコンテキストを含む辞書、見つからない場合は空の辞書
    """
    try:
        db = _db_client
        collection_ref = (
            db.collection("users")
            .document(email_of_the_conversation_partner)
            .collection("projectContexts")
        )

        docs = collection_ref.limit(1).stream()
        for doc in docs:
            if doc.exists:
                context = doc.to_dict()

                # projectInfo の DocumentReference を解決
                if "projectInfo" in context and hasattr(context["projectInfo"], "get"):
                    project_ref = context["projectInfo"]
                    project_doc = project_ref.get()
                    if project_doc.exists:
                        context["projectInfo"] = project_doc.to_dict()
                        context["projectInfo"]["id"] = project_doc.id

                        # members の userRef も解決
                        if "members" in context["projectInfo"]:
                            for member in context["projectInfo"]["members"]:
                                if isinstance(member, dict) and "userRef" in member:
                                    user_ref = member["userRef"]
                                    if hasattr(user_ref, "get"):
                                        user_doc = user_ref.get()
                                        if user_doc.exists:
                                            member["userRef"] = user_doc.to_dict()
                                            member["userRef"]["id"] = user_doc.id
                                        else:
                                            member["userRef"] = None
                    else:
                        # プロジェクトが見つからない場合はNoneに設定
                        context["projectInfo"] = None

                logger.info(context)
                return context

        return {}

    except Exception as e:
        print(f"Error retrieving user context: {str(e)}")
        return {"error": f"Failed to retrieve user context: {str(e)}"}


def firestore_get_user_context(email_of_the_conversation_partner: str) -> str:
    """
    Firestoreからユーザーコンテキストを取得する

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        str: 文字列形式のユーザーコンテキスト、見つからない場合は "None"
    """
    result = _get_user_context(email_of_the_conversation_partner)
    # 空の辞書の場合は "None" を返す（project_analyzer_agentのOptional[UserContext]として処理される）
    if not result or result == {}:
        return "None"
    return str(result)


def firestore_get_project_context(email_of_the_conversation_partner: str) -> str:
    """
    Firestoreからプロジェクトコンテキストを取得する

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        str: 文字列形式のプロジェクトコンテキスト、見つからない場合は "None"
    """
    result = _get_project_context(email_of_the_conversation_partner)
    print("------_get_project_context")
    print(result)
    # 空の辞書の場合は "None" を返す（project_analyzer_agentのOptional[UserContext]として処理される）
    if not result or result == {}:
        return "None"
    return str(result)


def _get_team_contexts(
    project_id: str, collection_name: str, order_by_created_at: bool = False
) -> list:
    """
    プロジェクトに参加している全メンバーのコンテキストを取得

    Args:
        project_id (str): 参画しているプロジェクトのID
        collection_name (str): 取得するコレクション名 ("userContexts" or "projectContexts")
        order_by_created_at (bool, optional): createdAtで降順ソートするか. Defaults to False.

    Returns:
        list: チームメンバー全員のコンテキストリスト
    """
    try:
        db = _db_client

        # プロジェクトドキュメントを取得
        project_doc = db.document(f"projects/{project_id}").get()
        if not project_doc.exists:
            print(f"❌ Project not found: {project_id}")
            return []

        members = project_doc.to_dict().get("members", [])
        print(f"👥 Found {len(members)} members in project {project_id}")

        team_contexts = []

        # 各メンバーのコンテキストを取得
        for member in members:
            try:
                # ユーザー参照を取得
                if hasattr(member, "path"):
                    user_ref = member
                elif isinstance(member, dict) and "userRef" in member:
                    user_ref = member["userRef"]
                else:
                    print(f"⚠️  Unexpected member format: {member}")
                    continue

                # users/{email}のDocumentReferenceから指定されたコレクションにアクセス
                user_doc_ref = user_ref.parent.parent  # userProfiles -> users/{email}

                # コレクションから最新のドキュメントを取得
                contexts_ref = user_doc_ref.collection(collection_name)

                if order_by_created_at:
                    docs = list(
                        contexts_ref.order_by(
                            "createdAt", direction=firestore.Query.DESCENDING
                        )
                        .limit(1)
                        .stream()
                    )
                else:
                    docs = list(contexts_ref.limit(1).stream())

                if docs and docs[0].exists:
                    context = docs[0].to_dict()
                    email = user_doc_ref.id
                    context["userEmail"] = email

                    # projectContexts の場合、projectInfo の DocumentReference を解決
                    if (
                        collection_name == "projectContexts"
                        and "projectInfo" in context
                        and hasattr(context["projectInfo"], "get")
                    ):
                        project_ref = context["projectInfo"]
                        project_doc = project_ref.get()
                        if project_doc.exists:
                            context["projectInfo"] = project_doc.to_dict()
                            context["projectInfo"]["id"] = project_doc.id

                            # members の userRef も解決
                            if "members" in context["projectInfo"]:
                                for member in context["projectInfo"]["members"]:
                                    if isinstance(member, dict) and "userRef" in member:
                                        member_user_ref = member["userRef"]
                                        if hasattr(member_user_ref, "get"):
                                            member_user_doc = member_user_ref.get()
                                            if member_user_doc.exists:
                                                member["userRef"] = (
                                                    member_user_doc.to_dict()
                                                )
                                                member["userRef"]["id"] = (
                                                    member_user_doc.id
                                                )
                                            else:
                                                member["userRef"] = None
                        else:
                            context["projectInfo"] = None

                    team_contexts.append(context)
                else:
                    email = (
                        user_doc_ref.id if hasattr(user_doc_ref, "id") else "unknown"
                    )

            except Exception as e:
                print(f"⚠️  Error processing member: {e}")
                continue

        print(f"📊 Retrieved {len(team_contexts)} {collection_name}")
        return team_contexts

    except Exception as e:
        print(f"❌ Error retrieving team {collection_name}: {e}")
        return []


def _get_team_project_contexts(project_id: str) -> list:
    """
    プロジェクトに参加している全メンバーのprojectContextを取得

    Args:
        project_id (str): 参画しているプロジェクトのID

    Returns:
        list: チームメンバー全員のプロジェクトコンテキストリスト
    """
    return _get_team_contexts(project_id, "projectContexts")


def _get_team_user_contexts(project_id: str) -> list:
    """
    プロジェクトに参加している全メンバーのuserContextを取得

    Args:
        project_id (str): 参画しているプロジェクトのID

    Returns:
        list: チームメンバー全員のユーザーコンテキストリスト
    """
    return _get_team_contexts(project_id, "userContexts", order_by_created_at=True)


def firestore_get_team_user_contexts(
    email_of_the_conversation_partner: str,
    project_id: str,
) -> str:
    """
    プロジェクトチーム全体のuserContextsを取得（リーダー向け）

    個人のuserContextとチームメンバー全員のuserContextsを含む包括的な情報を返します。
    この関数は、ユーザーがリーダーまたはサブリーダーの場合にのみ使用されることを想定しています。

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス
        project_id (str): 参画しているプロジェクトのID

    Returns:
        str: 個人のuserContextとチーム全体のuserContextsを含むJSON文字列
    """
    try:
        # 個人のuserContextを取得
        individual_context = _get_user_context(email_of_the_conversation_partner)

        if not individual_context or individual_context == {}:
            return "None"

        # チーム全体のuserContextsを取得
        team_contexts = _get_team_user_contexts(project_id)

        result = {
            "individual_context": individual_context,
            "team_contexts": team_contexts,
        }

        print(
            f"📊 Retrieved {len(team_contexts)} team user contexts for project {project_id}"
        )
        return str(result)

    except Exception as e:
        print(f"❌ Error retrieving team user contexts: {e}")
        return "None"


def firestore_get_project_members(project_id: str) -> str:
    """
    プロジェクトの全メンバーのuserContextsを取得（個人コンテキストチェックなし）

    アドバイススケジューラーがscan_all_users=Trueで実行される際に、
    各プロジェクトのメンバーリストを取得するために使用します。
    email_of_the_conversation_partnerパラメータが不要なため、システムから呼び出せます。

    Args:
        project_id (str): プロジェクトのID

    Returns:
        str: チームメンバー全員のuserContextsを含むJSON文字列
    """
    try:
        # チーム全体のuserContextsを取得
        team_contexts = _get_team_user_contexts(project_id)

        if not team_contexts:
            return "No members found"

        result = {"team_contexts": team_contexts}

        print(f"📊 Retrieved {len(team_contexts)} members for project {project_id}")
        return str(result)

    except Exception as e:
        print(f"❌ Error retrieving project members: {e}")
        return "No members found"


def firestore_get_team_project_contexts(
    email_of_the_conversation_partner: str,
    project_id: str,
) -> str:
    """
    プロジェクトチーム全体のprojectContextsを取得（リーダー向け）

    個人のprojectContextとチームメンバー全員のprojectContextsを含む包括的な情報を返します。
    この関数は、ユーザーがリーダーまたはサブリーダーの場合にのみ使用されることを想定しています。

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス
        project_id (str): 参画しているプロジェクトのID

    Returns:
        str: 個人のprojectContextとチーム全体のprojectContextsを含むJSON文字列
    """
    try:
        # 個人のprojectContextを取得
        individual_context = _get_project_context(email_of_the_conversation_partner)

        if not individual_context or individual_context == {}:
            return "None"

        # チーム全体のprojectContextsを取得
        team_contexts = _get_team_project_contexts(project_id)

        result = {
            "individual_context": individual_context,
            "team_contexts": team_contexts,
        }

        print(
            f"📊 Retrieved {len(team_contexts)} team project contexts for project {project_id}"
        )
        return str(result)

    except Exception as e:
        print(f"❌ Error retrieving team project contexts: {e}")
        return "None"


def _get_user_tasks(
    email_of_the_conversation_partner: str,
    project_id: Optional[str] = None,
    include_completed: bool = True,
) -> list[dict[str, Any]]:
    """
    ユーザーのタスクをFirestoreから取得する（新実装）

    特定のプロジェクトまたは全プロジェクトから、ユーザーに割り当てられている
    タスク（サブタスク含む）を取得します。

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス
        project_id (Optional[str], optional): プロジェクトID。Noneの場合は全プロジェクトから取得
        include_completed (bool, optional): 完了済みタスク(status="completed")を含めるか。デフォルトはTrue

    Returns:
        list[dict[str, Any]]: タスクとサブタスクのリスト
    """
    try:
        db = _db_client
        all_tasks = []

        # プロジェクトIDが指定されている場合は、そのプロジェクトのみ
        # 指定されていない場合は、ユーザーが参画している全プロジェクト
        if project_id:
            project_ids = [project_id]
            print(f"📊 Retrieving tasks for project: {project_id}")
        else:
            # ユーザーが参画している全プロジェクトを取得
            user_projects = _get_user_projects(email_of_the_conversation_partner)
            project_ids = [p["projectId"] for p in user_projects]
            print(f"📊 Retrieving tasks from {len(project_ids)} projects")

        # 各プロジェクトからタスクを取得
        for proj_id in project_ids:
            try:
                # プロジェクトドキュメントを取得してプロジェクト名を確認
                project_doc = db.collection("projects").document(proj_id).get()
                project_name = "Unknown Project"
                if project_doc.exists:
                    project_data = project_doc.to_dict()
                    project_name = project_data.get("projectName", proj_id)

                # プロジェクトのtasksコレクションを取得
                tasks_ref = (
                    db.collection("projects").document(proj_id).collection("tasks")
                )

                # 全タスクを取得
                for task_doc in tasks_ref.stream():
                    if not task_doc.exists:
                        continue

                    task_dict = task_doc.to_dict()

                    # タスクに割り当てられているメンバーを確認
                    assignee = task_dict.get("assignee", "")

                    # assigneeが文字列（メールアドレス）の場合
                    if isinstance(assignee, str):
                        is_assigned = assignee == email_of_the_conversation_partner
                    # assigneeが配列の場合（将来の互換性のため）
                    elif isinstance(assignee, list):
                        is_assigned = email_of_the_conversation_partner in assignee
                    else:
                        is_assigned = False

                    # このユーザーに割り当てられていない場合はスキップ
                    if not is_assigned:
                        continue

                    # 完了済みタスクをスキップ（include_completedがFalseの場合）
                    if not include_completed and task_dict.get("status") == "completed":
                        continue

                    # メタデータを追加
                    task_dict.update(
                        {
                            "taskId": task_doc.id,
                            "projectId": proj_id,
                            "projectName": project_name,
                            "taskPath": task_doc.reference.path,
                            "isSubTask": False,
                            "nestingLevel": 0,
                        }
                    )

                    all_tasks.append(task_dict)
                    print(
                        f"   📋 Found task: {task_dict.get('title', 'No title')} in project: {project_name}"
                    )

                    # サブタスクを再帰的に取得
                    subtasks = _get_subtasks_recursively(task_doc.reference, db)
                    for subtask in subtasks:
                        subtask["projectId"] = proj_id
                        subtask["projectName"] = project_name
                        all_tasks.append(subtask)

            except Exception as e:
                print(f"⚠️  Error retrieving tasks from project {proj_id}: {e}")
                continue

        print(f"📊 Retrieved {len(all_tasks)} tasks total")
        return all_tasks

    except Exception as e:
        print(f"❌ Error retrieving user tasks: {e}")
        return []


def firestore_get_user_tasks(
    email_of_the_conversation_partner: str,
    project_id: Optional[str] = None,
    include_completed: bool = True,
) -> str:
    """
    ユーザーのタスクをFirestoreから取得する

    特定のプロジェクトまたは全プロジェクトから、ユーザーに割り当てられている
    タスク（サブタスク含む）を取得します。

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス
        project_id (Optional[str], optional): プロジェクトID。Noneの場合は全プロジェクトから取得
        include_completed (bool, optional): 完了済みタスク(status="completed")を含めるか。デフォルトはTrue

    Returns:
        str: 文字列形式のタスクリスト、見つからない場合は "No tasks found"
    """
    result = _get_user_tasks(
        email_of_the_conversation_partner, project_id, include_completed
    )

    if not result:
        return "No tasks found"
    return str(result)


def _get_specific_task(
    project_id: str,
    task_id: str,
) -> dict[str, Any]:
    """
    Firestoreから特定のタスクを取得する

    Args:
        project_id (str): 参画しているプロジェクトのID
        task_id (str): タスクID

    Returns:
        dict[str, Any]: 特定のタスクを含む辞書、見つからない場合は空の辞書
    """
    try:
        db = _db_client

        # Get specific task document
        task_path = f"projects/{project_id}/tasks/{task_id}"

        task_doc = db.document(task_path)
        task_data = task_doc.get()

        if task_data.exists:
            task_dict = task_data.to_dict()
            task_dict["projectId"] = project_id
            task_dict["taskId"] = task_id
            task_dict["taskPath"] = task_path
            task_dict["isSubTask"] = False  # This is a parent task
            task_dict["nestingLevel"] = 0

            task_dict["subTasks"] = _get_subtasks_recursively(task_doc, db)
            return task_dict
        else:
            print(f"❌ Task not found at path: {task_path}")
            return {}

    except Exception as e:
        print(f"❌ Error retrieving specific task: {str(e)}")
        return {"error": f"Failed to retrieve task: {str(e)}"}


def firestore_get_specific_task(project_id: str, task_id: str) -> str:
    """
    Firestoreから特定のタスクを取得する

    Args:
        project_id (str): 参画しているプロジェクトのID
        task_id (str): タスクID

    Returns:
        str: 文字列形式のタスク情報、見つからない場合は "Task not found"
    """
    result = _get_specific_task(project_id, task_id)
    if not result or result == {}:
        return "Task not found"
    return str(result)


def _get_user_task_contexts(
    email_of_the_conversation_partner: str,
) -> list[dict[str, Any]]:
    """
    ユーザーの全taskContextsをFirestoreから取得する

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        list[dict[str, Any]]: 全プロジェクトのタスクコンテキストのリスト
    """
    try:
        db = _db_client

        # Get all taskEntities for the user
        task_entities_ref = (
            db.collection("users")
            .document(email_of_the_conversation_partner)
            .collection("taskEntities")
        )

        all_task_contexts = []

        for project_doc in task_entities_ref.stream():
            if not project_doc.exists:
                continue

            project_id = project_doc.id
            task_contexts_ref = project_doc.reference.collection("taskContexts")

            # Get all taskContexts for this project
            for task_context_doc in task_contexts_ref.stream():
                if not task_context_doc.exists:
                    continue

                task_context_dict = task_context_doc.to_dict()
                task_context_dict["taskContextId"] = task_context_doc.id
                task_context_dict["projectId"] = project_id

                # Convert relatedTasks DocumentReference to path string if it exists
                if "relatedTasks" in task_context_dict and hasattr(
                    task_context_dict["relatedTasks"], "path"
                ):
                    task_context_dict["relatedTasks"] = task_context_dict[
                        "relatedTasks"
                    ].path

                all_task_contexts.append(task_context_dict)

        print(f"📊 Retrieved {len(all_task_contexts)} task contexts")
        return all_task_contexts

    except Exception as e:
        print(f"❌ Error retrieving task contexts: {e}")
        return []


def firestore_get_user_task_contexts(email_of_the_conversation_partner: str) -> str:
    """
    ユーザーの全taskContextsをFirestoreから取得する

    taskContextsには、ユーザーが過去に実施したタスクでの行動履歴、成功・失敗体験、
    使用したツール、得られた成果などの学習情報が含まれています。

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        str: 文字列形式のタスクコンテキストリスト、見つからない場合は "No task contexts found"
    """
    result = _get_user_task_contexts(email_of_the_conversation_partner)

    if not result:
        return "No task contexts found"
    return str(result)


def _get_specific_subtask(
    project_id: str,
    parent_task_id: str,
    sub_task_id: str,
) -> dict[str, Any]:
    """
    Firestoreから特定のサブタスクを取得する

    Args:
        project_id (str): 参画しているプロジェクトのID
        parent_task_id (str): 親タスクのID
        sub_task_id (str): サブタスクのID

    Returns:
        dict[str, Any]: サブタスクを含む辞書、見つからない場合は空の辞書
    """
    try:
        db = _db_client

        # Get subtask document path: projects/{project_id}/tasks/{parent_task_id}/subTasks/{sub_task_id}
        subtask_path = (
            f"projects/{project_id}/tasks/{parent_task_id}/subTasks/{sub_task_id}"
        )

        subtask_doc = db.document(subtask_path)
        subtask_data = subtask_doc.get()

        if subtask_data.exists:
            subtask_dict = subtask_data.to_dict()
            subtask_dict["projectId"] = project_id
            subtask_dict["taskId"] = sub_task_id
            subtask_dict["parentTaskId"] = parent_task_id
            subtask_dict["taskPath"] = subtask_path
            subtask_dict["isSubTask"] = True
            subtask_dict["nestingLevel"] = 1

            # サブタスクの下にさらにサブタスクがある場合は再帰的に取得
            subtask_dict["subTasks"] = _get_subtasks_recursively(
                subtask_doc, db, level=2
            )

            print(f"📋 Retrieved subtask: {subtask_dict.get('title', 'No title')}")
            return subtask_dict
        else:
            print(f"❌ Subtask not found at path: {subtask_path}")
            return {}

    except Exception as e:
        print(f"❌ Error retrieving specific subtask: {str(e)}")
        return {"error": f"Failed to retrieve subtask: {str(e)}"}


def firestore_get_specific_subtask(
    project_id: str,
    parent_task_id: str,
    sub_task_id: str,
) -> str:
    """
    Firestoreから特定のサブタスクを取得する

    Args:
        project_id (str): 参画しているプロジェクトのID
        parent_task_id (str): 親タスクのID
        sub_task_id (str): サブタスクのID

    Returns:
        str: 文字列形式のサブタスク情報、見つからない場合は "Subtask not found"
    """
    result = _get_specific_subtask(project_id, parent_task_id, sub_task_id)
    if not result or result == {}:
        return "Subtask not found"
    return str(result)


def _get_user_projects(
    email_of_the_conversation_partner: str,
) -> list[dict[str, Any]]:
    """
    ユーザーが参画している全てのプロジェクトを取得する（ステータス問わず）

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        list[dict[str, Any]]: ユーザーが参画している全プロジェクトのリスト
    """
    try:
        db = _db_client

        # Get all projects (no status filter)
        projects_ref = db.collection("projects")

        user_projects = []

        for project_doc in projects_ref.stream():
            if not project_doc.exists:
                continue

            project_data = project_doc.to_dict()
            members = project_data.get("members", [])

            # Check if user is in members
            for member in members:
                # member can be a dict with userRef or a DocumentReference directly
                user_ref = None
                if isinstance(member, dict) and "userRef" in member:
                    user_ref = member["userRef"]
                elif hasattr(member, "path"):
                    user_ref = member

                # Check if userRef path contains the user's email
                if user_ref and hasattr(user_ref, "path"):
                    if email_of_the_conversation_partner in user_ref.path:
                        # Add project info
                        project_info = {
                            "projectId": project_doc.id,
                            "projectName": project_data.get(
                                "projectName", "Unnamed Project"
                            ),
                            "status": project_data.get("status", "unknown"),
                            "description": project_data.get("description", ""),
                        }
                        user_projects.append(project_info)
                        break  # Found the user, no need to check other members

        print(
            f"📊 Retrieved {len(user_projects)} projects for user {email_of_the_conversation_partner}"
        )
        return user_projects

    except Exception as e:
        print(f"❌ Error retrieving user projects: {e}")
        return []


def _get_user_info(
    user_email: str,
) -> dict[str, Any]:
    """
    Firestoreから特定のユーザー情報を取得する

    Args:
        user_email (str): ユーザーのメールアドレス

    Returns:
        dict[str, Any]: ユーザー情報を含む辞書、見つからない場合は空の辞書
    """
    try:
        db = _db_client

        # users/{email}/userProfiles から最新のプロファイルを取得
        # コレクションクエリとしてselectを使用
        docs = (
            db.collection("users")
            .document(user_email)
            .collection("userProfiles")
            .select(
                [
                    "displayName",
                    "nickname",
                ]
            )
            .limit(1)
            .stream()
        )

        for doc in docs:
            if doc.exists:
                user_info = doc.to_dict()
                return user_info

        print(f"❌ User not found")
        return {}

    except Exception as e:
        print(f"❌ Error retrieving user info: {str(e)}")
        return {"error": f"Failed to retrieve user info: {str(e)}"}


def firestore_get_user_projects(email_of_the_conversation_partner: str) -> str:
    """
    ユーザーが参画している全てのプロジェクトを取得する（ステータス問わず）

    プロジェクトIDが指定されていない状態でプロジェクトに関する質問があった場合に、
    ユーザーに選択肢を提示するために使用します。

    Args:
        email_of_the_conversation_partner (str): ユーザーのメールアドレス

    Returns:
        str: 文字列形式のプロジェクトリスト、見つからない場合は "No projects found"
    """
    result = _get_user_projects(email_of_the_conversation_partner)

    if not result:
        return "No projects found"
    return str(result)


def firestore_get_all_projects() -> str:
    """
    全てのプロジェクトを取得する（status="open"のみ）

    アドバイススケジューラーがscan_all_users=Trueで実行される際に、
    全プロジェクトのリストを取得するために使用します。
    活動中のユーザーを収集するため、statusが"open"のプロジェクトのみを返します。

    Returns:
        str: 文字列形式のプロジェクトリスト、見つからない場合は "No projects found"
    """
    logger.info("### firestore_get_all_projects start ###")
    try:
        db = _db_client

        # Get all projects with status="open"
        projects_ref = (
            db.collection("projects")
            .where("status", "==", "open")
            .select(["projectName", "status", "members", "projectOverview"])
        )

        all_projects = []

        for project_doc in projects_ref.stream():
            if not project_doc.exists:
                continue

            project_data = project_doc.to_dict()

            # 各メンバーにユーザー情報を追加
            if "members" in project_data:
                for member in project_data["members"]:
                    # userRefが有効な場合のみユーザー情報を追加
                    if "userRef" in member and hasattr(member["userRef"], "parent"):
                        # userRefのパスからemailを取得: users/{email}/userProfiles/{id}
                        user_email = member["userRef"].parent.parent.id
                        member["userInfo"] = _get_user_info(user_email)
                    # isOwnerは常に削除
                    member.pop("isOwner", None)
                    member.pop("userRef", None)

            # Add project info
            project_info = {
                "projectId": project_doc.id,
                "projectName": project_data.get("projectName", "Unnamed Project"),
                "status": project_data.get("status", "unknown"),
                "projectOverview": project_data.get("projectOverview", ""),
                "members": project_data.get("members", []),
            }
            all_projects.append(project_info)

        logger.info(f"📊 Retrieved {len(all_projects)} open projects")

        if not all_projects:
            return "No projects found"
        return str(all_projects)

    except Exception as e:
        print(f"❌ Error retrieving all projects: {e}")
        return "No projects found"


#############################################################################################
# Advice Queue Tools (Write Operations)
#############################################################################################
def firestore_create_advice_queue(
    user_email: str,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    advice_type: str = "",
    priority: int = 1,
    reason: str = "",
    suggested_time: str = "",
) -> str:
    """
    アドバイスキューをFirestoreに登録

    このツールは、アドバイススケジューラーが判定したアドバイス情報を
    FirestoreのadviceQueueコレクションに保存します。
    登録されたアドバイスは後で実行エージェントによって処理されます。

    Args:
        user_email (str): 対象ユーザーのメールアドレス
        project_id (Optional[str]): プロジェクトID（プロジェクト関連アドバイスの場合）
        task_id (Optional[str]): タスクID（タスク関連アドバイスの場合）
        advice_type (str): アドバイスタイプ (general/project/task/urgent/team_coordination)
        priority (int): 優先度 1-5（5が最高）
        reason (str): アドバイスが必要な理由（具体的に記載）
        suggested_time (str): 推奨実行時刻（ISO format, 例: "2025-01-15T10:00:00+09:00"）
                            **重要: 必ず9:00-18:00(JST)の範囲内で指定してください**

    Returns:
        str: 登録結果メッセージ

    Example:
        >>> firestore_create_advice_queue(
        ...     user_email="user@example.com",
        ...     project_id="proj123",
        ...     task_id="task456",
        ...     advice_type="urgent",
        ...     priority=5,
        ...     reason="設計レビューが遅延、3名をブロック中",
        ...     suggested_time="2025-01-15T10:00:00+09:00"
        ... )
        '✅ Advice queued for user@example.com (Priority 5, ID: abc123)'
    """
    try:
        db = _db_client

        # suggested_timeをtimestampに変換
        # ISO formatの文字列をdatetimeに変換（'Z'を'+00:00'に置換してUTC対応）
        advice_time_with_tz = datetime.fromisoformat(
            suggested_time.replace("Z", "+00:00")
        )
        logger.info(f"{advice_time_with_tz=}")

        # # JSTに変換して9:00-18:00の範囲内かチェック
        jst_time = advice_time_with_tz.astimezone(ZoneInfo("Asia/Tokyo"))
        logger.info(f"{jst_time=}")

        # 現在時刻を取得（過去時刻チェック用）
        # datetime.utcnow()ではなくdatetime.now(ZoneInfo("Asia/Tokyo"))を使用してJSTのaware datetimeを取得
        current_time = datetime.now(ZoneInfo("Asia/Tokyo"))

        # 過去時刻の自動調整ロジック
        # priorityに応じて未来の時刻に調整する分数を変える
        if jst_time <= current_time:
            # priorityによる調整幅の決定
            # priority 5 (最高): 5分後
            # priority 4: 10分後
            # priority 3: 15分後
            # priority 2: 20分後
            # priority 1 (最低): 30分後
            priority_to_delay = {
                5: 10,
                4: 15,
                3: 20,
                2: 25,
                1: 30,
            }
            delay_minutes = priority_to_delay.get(priority, 15)  # デフォルトは15分

            adjusted_jst_time = current_time + timedelta(minutes=delay_minutes)

            logger.warning(
                f"⚠️ Suggested time {suggested_time} is in the past. "
                f"Auto-adjusting to {adjusted_jst_time.isoformat()} "
                f"(current time: {current_time.isoformat()}, priority: {priority}, delay: {delay_minutes}min)"
            )

            jst_time = adjusted_jst_time

        hour = jst_time.hour

        if hour < 9 or hour >= 18:
            error_msg = f"❌ Invalid time: {suggested_time} (JST: {jst_time.strftime('%H:%M')}). Must be between 9:00-18:00 JST."
            logger.error(error_msg)
            return error_msg

        # advice_timeはJSTのaware datetimeのまま（Firestoreが自動的にUTCに変換して保存）
        advice_time = jst_time

        # Firestoreに保存するドキュメントデータ
        # Firestoreはaware datetimeを自動的にUTCに変換して保存し、取得時にタイムゾーン付きで復元
        doc_data = {
            "user_email": user_email,
            "project_id": project_id,
            "task_id": task_id,
            "advice_type": advice_type,
            "priority": priority,
            "reason": reason,
            "advice_time": advice_time,  # aware datetime (JST) → Firestoreが UTC に変換
            "status": "pending",  # pending/processing/completed/failed
            "created_at": current_time,  # aware datetime (JST) → Firestoreが UTC に変換
            "processed_at": None,
            "result": None,
        }

        # adviceQueueコレクションに追加
        doc_ref = db.collection("adviceQueue").add(doc_data)

        # 成功メッセージ
        doc_id = doc_ref[1].id
        logger.info(
            f"✅ Advice queued: {user_email} (Priority {priority}, ID: {doc_id})"
        )

        return f"✅ Advice queued for {user_email} (Priority {priority}, ID: {doc_id}, Time: {suggested_time})"

    except ValueError as e:
        # ISO format変換エラー
        error_msg = f"❌ Invalid time format: {suggested_time}. Use ISO format (e.g., '2025-01-15T10:00:00Z'). Error: {e}"
        logger.error(error_msg)
        return error_msg

    except Exception as e:
        # その他のエラー
        error_msg = f"❌ Error creating advice queue for {user_email}: {e}"
        logger.error(error_msg)
        return error_msg


def firestore_get_pending_advice_queue(
    user_email: Optional[str] = None, hours: int = 24
) -> str:
    """
    保留中(pending)または処理中(processing)のアドバイスキューを取得

    指定時間内の保留中・処理中のアドバイスを取得します。
    ユーザーメールを指定すると、そのユーザーのみに絞り込みます。

    Args:
        user_email (Optional[str]): 対象ユーザーのメールアドレス（Noneの場合は全ユーザー）
        hours (int): 取得対象の時間範囲（デフォルト24時間）

    Returns:
        str: アドバイスキューのJSON文字列

    Example:
        >>> firestore_get_pending_advice_queue(user_email="user@example.com")
        '[{"id": "abc123", "user_email": "user@example.com", "advice_type": "urgent", ...}]'
    """
    try:
        db = _db_client
        # 現在時刻をUTC aware datetimeで取得してJSTに変換
        current_time_jst = convert_utc_to_jst(datetime.now(dt_timezone.utc))
        threshold_time = current_time_jst - timedelta(hours=hours)

        logger.info(
            f"🔍 firestore_get_pending_advice_queue called: "
            f"user_email={user_email}, hours={hours}, "
            f"threshold_time={threshold_time.isoformat()}"
        )

        # インデックスに合わせたクエリ順序: status → user_email → created_at
        # インデックス: status (Ascending), user_email (Ascending), created_at (Ascending)
        query = db.collection("adviceQueue").where(
            "status", "in", ["pending", "processing"]
        )

        if user_email:
            query = query.where("user_email", "==", user_email)

        query = query.where("created_at", ">=", threshold_time)

        docs = list(query.stream())

        if not docs:
            logger.info(
                f"📋 No pending/processing advice found for {user_email or 'all users'}"
            )
            return "[]"

        # ドキュメントをJSON形式に変換
        import json

        advice_list = []
        for doc in docs:
            advice_data = doc.to_dict()
            advice_data["id"] = doc.id

            # datetimeオブジェクトをISO文字列に変換
            for key in ["advice_time", "created_at", "processed_at"]:
                if key in advice_data and advice_data[key]:
                    if isinstance(advice_data[key], datetime):
                        advice_data[key] = advice_data[key].isoformat()

            advice_list.append(advice_data)

        logger.info(
            f"📋 Found {len(advice_list)} pending/processing advice(s) for {user_email or 'all users'}"
        )

        # 各アドバイスの概要をログ出力
        for idx, advice in enumerate(advice_list, 1):
            logger.info(
                f"  [{idx}] ID: {advice.get('id')}, "
                f"Type: {advice.get('advice_type')}, "
                f"Reason: {advice.get('reason', '')[:50]}..."
            )

        return json.dumps(advice_list, ensure_ascii=False, indent=2)

    except Exception as e:
        error_msg = f"❌ Error getting pending advice queue: {e}"
        logger.error(error_msg)
        return "[]"


def firestore_update_advice_queue_status(
    queue_id: str, status: str, result: Optional[str] = None
) -> str:
    """
    adviceQueueのステータスを更新

    このツールは、アドバイス実行後にadviceQueueコレクションのドキュメントを更新します。
    処理結果を記録し、重複実行を防ぎます。

    Args:
        queue_id (str): adviceQueueのドキュメントID
        status (str): 更新後のステータス (processing/completed/failed)
        result (Optional[str]): 処理結果メッセージ（completed/failedの場合に設定）

    Returns:
        str: 更新結果メッセージ

    Example:
        >>> firestore_update_advice_queue_status(
        ...     queue_id="abc123",
        ...     status="completed",
        ...     result="アドバイスを正常に配信しました"
        ... )
        '✅ Advice queue abc123 updated to completed'
    """
    logger.info("### firestore_update_advice_queue_status start ###")
    try:
        db = _db_client

        # 更新データ
        update_data = {
            "status": status,
            "processed_at": convert_utc_to_jst(datetime.now(dt_timezone.utc)),
        }
        logger.info(f"{update_data=}")

        if result is not None:
            update_data["result"] = result

        # adviceQueueコレクションを更新
        db.collection("adviceQueue").document(queue_id).update(update_data)

        logger.info(f"✅ Advice queue {queue_id} updated to {status}")
        return f"✅ Advice queue {queue_id} updated to {status}"

    except Exception as e:
        error_msg = f"❌ Error updating advice queue {queue_id}: {e}"
        logger.error(error_msg)
        return error_msg


def firestore_create_project(
    user_email: str,
    project_name: Optional[str] = None,
    project_overview: Optional[str] = None,
    status: Optional[str] = "open",
    members: Optional[List[Dict[str, Any]]] = None,
    rules: Optional[List[Dict[str, Any]]] = None
) -> dict:
    """
    Firestore直接操作でプロジェクトを新規作成する (ADK Agent用レスポンス形式)
    ADK Function Calling互換性を重視したシンプル版
    """
    logger.info(f"Creating project via Firestore: {project_name}")
    
    # デフォルト値の処理
    if members is None:
        members = []
    if rules is None:
        rules = []
    if not project_name:
        return {"firestore_create_project_response": {"error": "プロジェクト名が必要です"}}
    
    # 空のオブジェクトをフィルタリング（ADKのFunction Calling制限への対応）
    if members:
        members = [m for m in members if m and any(m.values())]
        logger.debug(f"Filtered members: {members}")
    
    try:
        db = _db_client
        
        # JST timezone用のタイムスタンプ
        current_time = convert_utc_to_jst(datetime.now(dt_timezone.utc))
        
        #ADK Agent互換のシンプルなプロジェクトドキュメント構造
        project_data = {
            "projectName": project_name,
            "projectOverview": project_overview or "",
            "status": status or "open",
            "projectOwner": [user_email],
            "rules": rules,
            "createdAt": current_time,
            "updatedAt": current_time,
            "createdBy": user_email
        }
        
        # membersの処理: userRefをDocumentReferenceに変換
        processed_members = []
        if members:
            for member in members:
                if not member or not any(member.values()):
                    continue
                
                # Copy member dict to avoid modifying original
                m = dict(member)
                # userRefかemailのいずれかをメールアドレスとして取得
                user_email_member = m.get("userRef") or m.get("email")
                if isinstance(user_email_member, str) and "@" in user_email_member:
                    # users/{email}へのDocumentReferenceに変換
                    m["userRef"] = db.collection("users").document(user_email_member)
                    # emailキーが存在する場合は削除してuserRefに統一
                    if "email" in m:
                        del m["email"]
                
                processed_members.append(m)
        
        project_data["members"] = processed_members
        
        # Firestoreに保存 (空のドキュメントリファレンスを作成して自動生成されたIDを取得)
        doc_ref = db.collection("projects").document()
        project_id = doc_ref.id
        
        # ドキュメントにprojectIdを含める
        project_data["projectId"] = project_id
        
        # 保存実行
        doc_ref.set(project_data)
        
        # デバッグ情報をログ出力
        logger.info(f"✅ Project created successfully:")
        logger.info(f"   - Project ID: {project_id}")
        logger.info(f"   - Project Name: {project_name}")
        logger.info(f"   - Firestore Path: projects/{project_id}")
        logger.info(f"   - DATABASE: {FIRESTORE_DATABASE}")
        logger.info(f"   - PROJECT_ID: {PROJECT_ID}")
        logger.info(f"   - Document Data: {project_data}")
        
        return {
            "firestore_create_project_response": {
                "project": {
                    "projectId": project_id,
                    "projectName": project_name
                }
            }
        }
        
    except Exception as e:
        error_msg = f"Failed to create project: {str(e)}"
        logger.error(error_msg)
        return {"firestore_create_project_response": {"error": error_msg}}


def firestore_get_all_projects() -> dict:
    """
    Firestore直接操作で全プロジェクトを取得する (ADK Agent用レスポンス形式)
    """
    logger.info("Getting all projects via Firestore")
    
    try:
        db = _db_client
        
        # projectsコレクションから全ドキュメントを取得
        projects_ref = db.collection("projects")
        docs = projects_ref.stream()
        
        projects = []
        for doc in docs:
            project_data = doc.to_dict()
            # FirestoreオブジェクトをJSON化可能な形式に変換
            cleaned_data = _clean_firestore_data(project_data)
            projects.append(cleaned_data)
        
        logger.info(f"✅ Retrieved {len(projects)} projects")
        
        return {
            "firestore_get_all_projects_response": {
                "projects": projects,
                "count": len(projects)
            }
        }
        
    except Exception as e:
        error_msg = f"Failed to get projects: {str(e)}"
        logger.error(error_msg)
        return {
            "firestore_get_all_projects_response": {
                "error": error_msg,
                "projects": [],
                "count": 0
            }
        }


def firestore_update_project(
    project_id: str,
    project_name: Optional[str] = None,
    status: Optional[str] = None,
    project_overview: Optional[str] = None,
    members: Optional[List[Dict[str, Any]]] = None,
    rules: Optional[List[Dict[str, Any]]] = None,
    user_email: str = "unknown@example.com"
) -> dict:
    """
    Firestore直接操作でプロジェクトを更新する (ADK Agent用レスポンス形式)
    """
    logger.info(f"Updating project via Firestore: {project_id}")
    
    if not project_id:
        return {"firestore_update_project_response": {"error": "project_id is required"}}
    
    try:
        db = _db_client
        
        # 更新データを構築
        update_data = {
            "updatedAt": convert_utc_to_jst(datetime.now(dt_timezone.utc)),
            "updatedBy": user_email
        }
        
        if project_name is not None:
            update_data["projectName"] = project_name
        if status is not None:
            update_data["status"] = status
        if project_overview is not None:
            update_data["projectOverview"] = project_overview
        if members is not None:
            # userRefをDocumentReferenceに変換
            processed_members = []
            for member in members:
                if not member or not any(member.values()):
                    continue
                
                # Copy member dict to avoid modifying original
                m = dict(member)
                # userRefかemailのいずれかをメールアドレスとして取得
                user_email_member = m.get("userRef") or m.get("email")
                if isinstance(user_email_member, str) and "@" in user_email_member:
                    # users/{email}へのDocumentReferenceに変換
                    m["userRef"] = db.collection("users").document(user_email_member)
                    # emailキーが存在する場合は削除してuserRefに統一
                    if "email" in m:
                        del m["email"]
                processed_members.append(m)
            update_data["members"] = processed_members
        if rules is not None:
            update_data["rules"] = rules
        
        # Firestoreドキュメントを更新
        project_ref = db.collection("projects").document(project_id)
        project_ref.update(update_data)
        
        logger.info(f"✅ Project updated successfully: {project_id}")
        
        return {
            "firestore_update_project_response": {
                "project": {
                    "projectId": project_id,
                    "updated_fields": list(update_data.keys())
                }
            }
        }
        
    except Exception as e:
        error_msg = f"Failed to update project: {str(e)}"
        logger.error(error_msg)
        return {"firestore_update_project_response": {"error": error_msg}}
