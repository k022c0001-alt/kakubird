# api/services/llm/PromptBuilder.py

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class PromptBuilder:
    """
    LocalLLMEngine に渡すメッセージ配列を構築する。

    ============================================================
    Chat
    ============================================================

    ConversationState
        ↓
    PromptBuilder
        ↓
    LocalLLMEngine.chat()

    ============================================================
    Project Planning
    ============================================================

    RequirementAnalyzer
        ↓
    project_context
        ↓
    PromptBuilder
        ↓
    LocalLLMEngine.chat()
        ↓
    JSON
        ↓
    ProjectPlanner
        ↓
    BuildPlan

    ============================================================
    方針
    ============================================================

    - LocalLLM固有のChat Templateを手書きしない
    - role/content形式のmessagesを返す
    - llama-cpp-python側へモデル固有形式の変換を任せる
    - Project PlanningではJSONのみを出力させる
    """

    # ========================================================
    # Chat Prompt
    # ========================================================

    def build_chat_messages(
        self,
        user_message: str,
        state: Any,
        analysis: Optional[Dict[str, Any]] = None,
        summary: Optional[Dict[str, Any]] = None,
        knowledge_data: Optional[List[Any]] = None,
    ) -> List[Dict[str, str]]:
        """
        通常会話・質問応答用のmessagesを生成する。

        Parameters
        ----------
        user_message:
            最新のユーザー入力。

        state:
            ConversationState。

        analysis:
            IntentInspectorの結果。

        summary:
            ConversationSummaryの結果。

        knowledge_data:
            KnowledgeLoader等から取得したJSON Knowledge。
        """

        analysis = analysis or {}
        summary = summary or {}
        knowledge_data = knowledge_data or []

        # ----------------------------------------------------
        # 1. System
        # ----------------------------------------------------

        system_content = (
            self._build_chat_system_prompt(
                state=state,
                analysis=analysis,
                summary=summary,
                knowledge_data=knowledge_data,
            )
        )

        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": system_content,
            }
        ]

        # ----------------------------------------------------
        # 2. Recent History
        # ----------------------------------------------------

        history = getattr(
            state,
            "history",
            [],
        )

        if history:

            recent_history = history[-5:]

            for msg in recent_history:

                role, content = (
                    self._extract_history_message(
                        msg
                    )
                )

                if not content:
                    continue

                messages.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

        # ----------------------------------------------------
        # 3. Current User
        # ----------------------------------------------------

        current_message = str(
            user_message or ""
        ).strip()

        if current_message:

            # history末尾に同一メッセージが既に存在する場合、
            # 二重追加を防止する。
            should_append = True

            if messages:

                last_message = messages[-1]

                if (
                    last_message.get("role")
                    == "user"
                    and last_message.get("content")
                    == current_message
                ):
                    should_append = False

            if should_append:

                messages.append(
                    {
                        "role": "user",
                        "content": current_message,
                    }
                )

        return messages

    # ========================================================
    # Chat System Prompt
    # ========================================================

    def _build_chat_system_prompt(
        self,
        state: Any,
        analysis: Dict[str, Any],
        summary: Dict[str, Any],
        knowledge_data: List[Any],
    ) -> str:
        """
        通常会話用System Prompt。

        JSON KnowledgeとConversationStateを優先し、
        ハルシネーションを抑える。
        """

        rules: List[str] = [
            "あなたはローカルで動作しているAIアシスタントです。",
            "",
            "【最重要ルール】",
            "- ユーザーが発言していない内容を事実として追加しない。",
            "- 存在しない過去の会話を作らない。",
            "- 不確かな情報や推測を断定しない。",
            "- 不明な場合は「不明」「わからない」と回答してよい。",
            "- facts と user_opinions を混同しない。",
            "- 提供されたJSON Knowledgeが存在する場合は、それを優先する。",
            "- 現在のIntent・Topic・ConversationStateを尊重する。",
            "- 内部状態を勝手に変更したことにしない。",
        ]

        # ----------------------------------------------------
        # Conversation State
        # ----------------------------------------------------

        rules.append(
            "\n【現在の会話状態】"
        )

        current_topic = getattr(
            state,
            "current_topic",
            None,
        )

        previous_topic = getattr(
            state,
            "previous_topic",
            None,
        )

        current_intent = getattr(
            state,
            "current_intent",
            None,
        )

        previous_intent = getattr(
            state,
            "previous_intent",
            None,
        )

        if current_topic:

            rules.append(
                f"- 現在の話題 (Topic): "
                f"{current_topic}"
            )

        if previous_topic:

            rules.append(
                f"- 前の話題: "
                f"{previous_topic}"
            )

        if current_intent:

            rules.append(
                f"- 現在の意図 (Intent): "
                f"{current_intent}"
            )

        if previous_intent:

            rules.append(
                f"- 前の意図: "
                f"{previous_intent}"
            )

        # ----------------------------------------------------
        # IntentInspector
        # ----------------------------------------------------

        if analysis:

            rules.append(
                "\n【IntentInspector Analysis】"
            )

            rules.append(
                self._safe_json_dumps(
                    analysis
                )
            )

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        if summary:

            rules.append(
                "\n【Conversation Summary】"
            )

            rules.append(
                self._safe_json_dumps(
                    summary
                )
            )

        # ----------------------------------------------------
        # Facts
        # ----------------------------------------------------

        facts = getattr(
            state,
            "facts",
            {},
        )

        if facts:

            rules.append(
                "\n【確認済みFacts】"
            )

            rules.append(
                self._safe_json_dumps(
                    facts
                )
            )

        # ----------------------------------------------------
        # User Opinions
        # ----------------------------------------------------

        user_opinions = getattr(
            state,
            "user_opinions",
            {},
        )

        if user_opinions:

            rules.append(
                "\n【ユーザーの意見・好み】"
            )

            rules.append(
                self._safe_json_dumps(
                    user_opinions
                )
            )

        # ----------------------------------------------------
        # Project Context
        # ----------------------------------------------------

        project_context = getattr(
            state,
            "project_context",
            {},
        )

        if (
            isinstance(
                project_context,
                dict,
            )
            and self._has_meaningful_values(
                project_context
            )
        ):

            rules.append(
                "\n【進行中のプロジェクト要件】"
            )

            rules.append(
                self._safe_json_dumps(
                    project_context
                )
            )

            rules.append(
                "- このProject Contextは過去の会話で"
                "確認されたアプリ要件として扱ってください。"
            )

            rules.append(
                "- ユーザーが明示していない要件を"
                "確定事項として追加しないでください。"
            )

        # ----------------------------------------------------
        # Knowledge
        # ----------------------------------------------------

        if knowledge_data:

            rules.append(
                "\n【提供された知識 (Knowledge)】"
            )

            rules.append(
                self._safe_json_dumps(
                    knowledge_data
                )
            )

            rules.append(
                "- 上記Knowledgeに書かれている内容を"
                "最優先して回答してください。"
            )

        return "\n".join(
            rules
        )

    # ========================================================
    # History Utility
    # ========================================================

    def _extract_history_message(
        self,
        msg: Any,
    ) -> tuple[str, str]:
        """
        ConversationState.history 内のmessageを

        - dict
        - ConversationMessageなどのobject

        の両方から安全に読み取る。
        """

        if isinstance(
            msg,
            dict,
        ):

            role = msg.get(
                "role",
                "user",
            )

            content = str(
                msg.get(
                    "content",
                    "",
                )
            ).strip()

        else:

            role = getattr(
                msg,
                "role",
                "user",
            )

            content = str(
                getattr(
                    msg,
                    "content",
                    "",
                )
            ).strip()

        role = str(
            role or "user"
        ).lower()

        if role not in (
            "user",
            "assistant",
        ):

            role = "user"

        return (
            role,
            content,
        )

    # ========================================================
    # Project Planning
    # ========================================================

    def build_planning_messages(
        self,
        project_context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        """
        RequirementAnalyzerが作ったproject_contextから
        ProjectPlanner向け設計JSONを生成するmessagesを構築する。
        """

        context = (
            project_context
            if isinstance(
                project_context,
                dict,
            )
            else {}
        )

        system_content = (
            self._build_planning_system_prompt()
        )

        user_content = (
            self._build_planning_user_prompt(
                context
            )
        )

        return [
            {
                "role": "system",
                "content": system_content,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]

    # ========================================================
    # Planning System Prompt
    # ========================================================

    def _build_planning_system_prompt(
        self,
    ) -> str:
        """
        ProjectPlannerへ渡すJSONだけを生成させる。

        BuildPlanとの整合性を優先する。
        """

        return """
あなたはアプリケーション設計を担当する
ソフトウェアアーキテクトです。

ユーザーとの会話から抽出済みの
Project Contextを読み取り、
実際にファイル生成へ利用できる
Project Build Planを作成してください。

【最重要ルール】

- 回答は必ず有効なJSONのみで返してください。
- Markdownコードブロックを使用しないでください。
- ```json や ``` を出力しないでください。
- 挨拶、説明、補足、謝罪をJSONの外側へ書かないでください。
- Project Contextに存在しない要件を勝手に確定しないでください。
- 不明な値を無理に推測しないでください。
- 必要な場合は null、[]、{} を使用してください。
- file_structure内には実際に生成すべきファイルだけを入れてください。
- directoryだけのエントリーは作らないでください。
- pathはプロジェクトルートからの相対パスにしてください。
- 同じpathを重複させないでください。


【Frameworkルール】

Reactの場合、最低限以下のファイルを設計してください。

- package.json
- index.html
- src/main.jsx
- src/App.jsx
- src/index.css

Next.jsの場合はNext.jsの標準的な構成を使用してください。

HTMLの場合は最低限、

- index.html
- style.css
- script.js

を検討してください。


【dependencies】

アプリ実行に必要なnpm packageのみを
dependenciesへ入れてください。

例:

[
  "react",
  "react-dom"
]


【dev_dependencies】

開発・ビルド専用packageを入れてください。

例:

[
  "vite",
  "@vitejs/plugin-react"
]


【scripts】

package.jsonで使用するnpm scriptsを
key/value形式で指定してください。

例:

{
  "dev": "vite",
  "build": "vite build",
  "preview": "vite preview"
}


【出力JSONスキーマ】

{
  "project_name": "my-app",

  "description": "アプリの概要",

  "framework": "react",

  "features": [
    "favorite",
    "short_video"
  ],

  "pages": [
    "home",
    "feed",
    "detail"
  ],

  "database": null,

  "backend": null,

  "design_preferences": [],

  "constraints": [],

  "dependencies": [
    "react",
    "react-dom"
  ],

  "dev_dependencies": [
    "vite",
    "@vitejs/plugin-react"
  ],

  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },

  "file_structure": [
    {
      "path": "package.json",
      "type": "file",
      "description": "npm dependenciesとscriptsを定義する"
    },
    {
      "path": "index.html",
      "type": "file",
      "description": "ViteアプリのHTMLエントリーポイント"
    },
    {
      "path": "src/main.jsx",
      "type": "file",
      "description": "ReactアプリをDOMへmountする"
    },
    {
      "path": "src/App.jsx",
      "type": "file",
      "description": "アプリ全体のルートコンポーネント"
    },
    {
      "path": "src/index.css",
      "type": "file",
      "description": "アプリ全体の基本スタイル"
    }
  ]
}


【設計品質】

file_structureのdescriptionは
FileGeneratorが後からコード生成に利用します。

そのため、

「コンポーネント」

だけではなく、

「職業ショート動画を縦方向に表示し、
お気に入り操作をJobCardへ渡すコンポーネント」

のように、

- 役割
- 表示内容
- 主要な責務
- 他ファイルとの関係

がわかる具体的な説明を書いてください。
""".strip()

    # ========================================================
    # Planning User Prompt
    # ========================================================

    def _build_planning_user_prompt(
        self,
        project_context: Dict[str, Any],
    ) -> str:
        """
        RequirementAnalyzerで蓄積したProject Contextを渡す。
        """

        requirements = (
            self._safe_json_dumps(
                project_context
            )
        )

        return f"""
以下はユーザーとの会話から収集した
Project Contextです。

【Project Context】

{requirements}

このProject Contextを元に、
アプリケーションのBuild Planを作成してください。

注意:

- ユーザーが指定済みのframeworkを変更しない。
- target_userを設計へ反映する。
- featuresをfile_structureへ反映する。
- pagesが指定されている場合は、それぞれの画面構成を考慮する。
- databaseが指定されている場合のみデータベース構成を設計する。
- backendが指定されている場合のみバックエンド構成を設計する。
- design_preferencesをUI設計へ反映する。
- constraintsを必ず守る。
- raw_requirementsはユーザーの元発言として参考にする。
- missing_requirementsは未確定項目である。
- 未確定項目を根拠なく確定しない。
- BuildPlanとしてそのまま利用できるJSONを返す。

必ず指定されたJSONスキーマに従ってください。
""".strip()

    # ========================================================
    # JSON Utility
    # ========================================================

    @staticmethod
    def _safe_json_dumps(
        value: Any,
    ) -> str:
        """
        Promptへ安全にJSONを埋め込む。
        """

        try:

            return json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        except Exception:

            return str(
                value
            )

    # ========================================================
    # Context Utility
    # ========================================================

    @staticmethod
    def _has_meaningful_values(
        context: Dict[str, Any],
    ) -> bool:
        """
        DEFAULT_PROJECT_CONTEXTだけ存在していて、
        全値が空の場合にはPromptへ不要なProject Contextを
        入れないための判定。
        """

        for value in context.values():

            if value not in (
                None,
                "",
                [],
                {},
                False,
            ):

                return True

        return False


# ============================================================
# Standalone Test
# ============================================================

if __name__ == "__main__":

    class MockState:

        current_topic = (
            "Reactアプリ開発"
        )

        previous_topic = None

        current_intent = (
            "follow_up"
        )

        previous_intent = None

        facts = {}

        user_opinions = {}

        project_context = {
            "project_name":
                "mikke-career",

            "framework":
                "react",

            "purpose":
                "中学生が職業を発見する",

            "description":
                "中学生向け職業発見アプリ",

            "target_user":
                "中学生",

            "features": [
                "short_video",
                "favorite",
            ],

            "pages": [
                "home",
                "feed",
                "detail",
            ],

            "database":
                None,

            "backend":
                None,

            "design_preferences":
                [],

            "constraints":
                [],

            "raw_requirements": [
                "Reactで中学生向けのアプリを作りたい",
                "ショート動画とお気に入りを入れたい",
            ],

            "missing_requirements":
                [],

            "ready_to_plan":
                True,
        }

        history = [
            {
                "role":
                    "user",

                "content":
                    "Reactで中学生向けのアプリを作りたい",
            },
            {
                "role":
                    "assistant",

                "content":
                    "どのような機能が必要ですか？",
            },
        ]

    builder = PromptBuilder()

    # ========================================================
    # Chat Test
    # ========================================================

    print(
        "=== Chat Messages Test ==="
    )

    chat_msgs = (
        builder.build_chat_messages(
            user_message=
                "ショート動画とお気に入り機能を入れて。",

            state=
                MockState(),

            analysis={
                "intent":
                    "follow_up",

                "mode":
                    "general_chat",
            },

            summary={
                "current_topic":
                    "Reactアプリ開発"
            },

            knowledge_data=[
                {
                    "title":
                        "React動画再生",

                    "content":
                        "videoタグを使用します。",
                }
            ],
        )
    )

    print(
        json.dumps(
            chat_msgs,
            ensure_ascii=False,
            indent=2,
        )
    )

    # ========================================================
    # Planning Test
    # ========================================================

    print(
        "\n=== Planning Messages Test ==="
    )

    plan_msgs = (
        builder.build_planning_messages(
            project_context=
                MockState.project_context
        )
    )

    print(
        json.dumps(
            plan_msgs,
            ensure_ascii=False,
            indent=2,
        )
    )