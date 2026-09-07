# api/services/project_generation/RequirementAnalyzer.py

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class RequirementAnalyzer:
    """
    ユーザーとの会話からアプリ開発要件を構造化する。

    方針:
    - LLMなしでも動作する
    - 否定表現を優先する
    - 複数ターンでcontextを育てる
    - 明示された自由記述も可能な範囲で構造化する
    - 辞書にない機能をraw_featuresとして保持できる
    """

    # ========================================================
    # Framework
    # ========================================================

    FRAMEWORKS = {
        "react": [
            "react",
            "jsx",
        ],
        "nextjs": [
            "next.js",
            "nextjs",
            "next js",
        ],
        "vue": [
            "vue",
        ],
        "html": [
            "html",
            "vanilla js",
            "vanilla javascript",
        ],
        "fastapi": [
            "fastapi",
        ],
        "flask": [
            "flask",
        ],
    }

    # ========================================================
    # Features
    # ========================================================

    FEATURES = {
        "authentication": [
            "ログイン",
            "認証",
            "アカウント",
            "サインイン",
            "sign in",
            "login",
        ],
        "favorite": [
            "お気に入り",
            "ブックマーク",
            "favorite",
        ],
        "search": [
            "検索",
            "探す",
            "search",
        ],
        "short_video": [
            "ショート動画",
            "short video",
            "shortvideo",
            "tiktok",
            "tik tok",
        ],
        "chat": [
            "チャット",
            "aiチャット",
            "ai chat",
        ],
        "calendar": [
            "カレンダー",
            "予定",
            "スケジュール",
            "calendar",
        ],
        "database": [
            "データベース",
            "database",
            "db",
        ],
        "recommendation": [
            "おすすめ",
            "推薦",
            "レコメンド",
            "recommend",
            "recommendation",
        ],
        "history": [
            "履歴",
            "視聴履歴",
            "history",
        ],
        "profile": [
            "プロフィール",
            "profile",
        ],
        "ranking": [
            "ランキング",
            "順位",
            "ranking",
        ],
        "filter": [
            "絞り込み",
            "フィルター",
            "filter",
        ],
        "notification": [
            "通知",
            "notification",
        ],
        "completion": [
            "完了状態",
            "完了にする",
            "完了する",
            "読み終わった",
            "完了管理",
        ],
        "list": [
            "一覧表示",
            "一覧にする",
            "リスト表示",
            "一覧",
        ],
        "create": [
            "追加する",
            "登録する",
            "新規作成",
            "作成する",
        ],
        "delete": [
            "削除する",
            "削除",
            "delete",
        ],
        "edit": [
            "編集する",
            "編集",
            "更新する",
            "update",
        ],
    }

    # ========================================================
    # Pages
    # ========================================================

    PAGES = {
        "home": [
            "ホーム画面",
            "ホーム",
            "home",
            "トップページ",
            "トップ画面",
        ],
        "feed": [
            "フィード",
            "feed",
            "動画一覧",
            "ショート動画画面",
        ],
        "list": [
            "一覧画面",
            "一覧ページ",
            "リスト画面",
            "list page",
        ],
        "detail": [
            "詳細画面",
            "詳細ページ",
            "detail",
        ],
        "login": [
            "ログイン画面",
            "login page",
        ],
        "signup": [
            "新規登録画面",
            "登録画面",
            "signup",
            "sign up",
        ],
        "profile": [
            "プロフィール画面",
            "profile page",
        ],
        "settings": [
            "設定画面",
            "settings",
        ],
        "search": [
            "検索画面",
            "search page",
        ],
        "favorite": [
            "お気に入り画面",
            "保存一覧",
            "favorites",
        ],
        "about": [
            "about",
            "概要ページ",
            "説明ページ",
        ],
    }

    # ========================================================
    # Database
    # ========================================================

    DATABASES = {
        "sqlite": ["sqlite"],
        "postgresql": ["postgresql", "postgres"],
        "supabase": ["supabase"],
        "mysql": ["mysql"],
        "firebase": ["firebase", "firestore"],
    }

    # ========================================================
    # Backend
    # ========================================================

    BACKENDS = {
        "fastapi": ["fastapi"],
        "flask": ["flask"],
        "node": [
            "node.js",
            "nodejs",
            "node js",
            "express",
        ],
        "supabase": ["supabase"],
        "firebase": ["firebase"],
    }

    # ========================================================
    # Design
    # ========================================================

    DESIGN_PREFERENCES = {
        "dark": [
            "ダーク",
            "暗め",
            "dark mode",
            "dark",
        ],
        "light": [
            "明るい",
            "ライト",
            "light mode",
        ],
        "simple": [
            "シンプル",
            "simple",
        ],
        "modern": [
            "モダン",
            "modern",
        ],
        "colorful": [
            "カラフル",
            "colorful",
        ],
        "minimal": [
            "ミニマル",
            "minimal",
        ],
        "mobile_first": [
            "スマホ向け",
            "スマートフォン向け",
            "スマートフォンでも見やすく",
            "モバイル向け",
            "mobile first",
            "mobile-first",
        ],
    }

    # ========================================================
    # Constraints
    # ========================================================

    CONSTRAINTS = {
        "no_ai": [
            "aiを使わない",
            "生成aiを使わない",
            "aiは不要",
        ],
        "offline": [
            "オフライン",
            "offline",
        ],
        "no_database": [
            "データベースなし",
            "データベース不要",
            "データベースは不要",
            "dbなし",
            "db不要",
            "databaseなし",
            "database不要",
        ],
        "frontend_only": [
            "フロントだけ",
            "フロントエンドだけ",
            "frontend only",
        ],
        "no_login": [
            "ログインなし",
            "ログイン不要",
            "ログイン機能は不要",
            "認証なし",
            "認証不要",
            "アカウント不要",
        ],
        "free_only": [
            "無料だけ",
            "無料で",
            "free only",
        ],
    }

    # ========================================================
    # Negation
    # ========================================================

    NEGATION_WORDS = (
        "不要",
        "なし",
        "いらない",
        "要らない",
        "必要ない",
        "使わない",
        "使用しない",
        "含めない",
        "つけない",
        "付けない",
        "実装しない",
        "今回は不要",
        "今回はなし",
    )

    # ========================================================
    # Target Users
    # ========================================================

    TARGET_USERS = (
        "小学生",
        "中学生",
        "高校生",
        "大学生",
        "専門学生",
        "専門学校生",
        "社会人",
        "教師",
        "先生",
        "企業",
        "学校",
        "自治体",
        "一般ユーザー",
    )

    # ========================================================
    # Analyze
    # ========================================================

    def analyze(
        self,
        message: str,
        current_context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Dict[str, Any]:

        context = dict(
            current_context
            or {}
        )

        self._ensure_defaults(
            context
        )

        text = str(
            message or ""
        ).strip()

        lowered = text.lower()

        if not text:

            self._update_completeness(
                context
            )

            return context

        # ----------------------------------------------------
        # Explicit constraints first
        # ----------------------------------------------------

        detected_constraints = (
            self._detect_constraints(
                lowered
            )
        )

        context["constraints"] = (
            self._merge_list(
                context.get(
                    "constraints",
                    [],
                ),
                detected_constraints,
            )
        )

        # ----------------------------------------------------
        # Project Name
        # ----------------------------------------------------

        project_name = (
            self._detect_project_name(
                text
            )
        )

        if project_name:

            context[
                "project_name"
            ] = project_name

        # ----------------------------------------------------
        # Framework
        # ----------------------------------------------------

        framework = (
            self._detect_framework(
                lowered
            )
        )

        if framework:

            context[
                "framework"
            ] = framework

        # ----------------------------------------------------
        # Target User
        # ----------------------------------------------------

        target_user = (
            self._detect_target(
                text
            )
        )

        if target_user:

            context[
                "target_user"
            ] = target_user

        # ----------------------------------------------------
        # Purpose
        # ----------------------------------------------------

        purpose = (
            self._detect_purpose(
                text
            )
        )

        if purpose:

            context[
                "purpose"
            ] = purpose

        # ----------------------------------------------------
        # Description
        # ----------------------------------------------------

        description = (
            self._detect_description(
                text,
                context,
            )
        )

        if description:

            context[
                "description"
            ] = description

        # ----------------------------------------------------
        # Features
        # ----------------------------------------------------

        detected_features = (
            self._detect_features(
                text
            )
        )

        context[
            "features"
        ] = self._merge_list(
            context.get(
                "features",
                [],
            ),
            detected_features,
        )

        # 自由記述の箇条書き機能も保持
        raw_features = (
            self._detect_raw_features(
                text
            )
        )

        context[
            "raw_features"
        ] = self._merge_list(
            context.get(
                "raw_features",
                [],
            ),
            raw_features,
        )

        # ----------------------------------------------------
        # Pages
        # ----------------------------------------------------

        detected_pages = (
            self._detect_pages(
                text
            )
        )

        context[
            "pages"
        ] = self._merge_list(
            context.get(
                "pages",
                [],
            ),
            detected_pages,
        )

        raw_pages = (
            self._detect_raw_pages(
                text
            )
        )

        context[
            "raw_pages"
        ] = self._merge_list(
            context.get(
                "raw_pages",
                [],
            ),
            raw_pages,
        )

        # ----------------------------------------------------
        # Database
        # ----------------------------------------------------

        database = (
            self._detect_database(
                text
            )
        )

        if database is not None:

            context[
                "database"
            ] = database

        # ----------------------------------------------------
        # Backend
        # ----------------------------------------------------

        backend = (
            self._detect_backend(
                text
            )
        )

        if backend is not None:

            context[
                "backend"
            ] = backend

        # ----------------------------------------------------
        # Design
        # ----------------------------------------------------

        detected_design = (
            self._detect_design_preferences(
                lowered
            )
        )

        context[
            "design_preferences"
        ] = self._merge_list(
            context.get(
                "design_preferences",
                [],
            ),
            detected_design,
        )

        # ----------------------------------------------------
        # Apply constraints after detections
        # ----------------------------------------------------

        self._apply_constraints(
            context
        )

        # ----------------------------------------------------
        # Original Requirements
        # ----------------------------------------------------

        requirements = list(
            context.get(
                "raw_requirements",
                [],
            )
            or []
        )

        if (
            text
            and text not in requirements
        ):

            requirements.append(
                text
            )

        context[
            "raw_requirements"
        ] = requirements[-30:]

        # ----------------------------------------------------
        # Completeness
        # ----------------------------------------------------

        self._update_completeness(
            context
        )

        return context

    # ========================================================
    # Defaults
    # ========================================================

    def _ensure_defaults(
        self,
        context: Dict[str, Any],
    ) -> None:

        defaults = {
            "project_name": None,
            "framework": None,
            "purpose": None,
            "description": None,
            "target_user": None,
            "features": [],
            "raw_features": [],
            "pages": [],
            "raw_pages": [],
            "database": None,
            "backend": None,
            "design_preferences": [],
            "constraints": [],
            "raw_requirements": [],
            "missing_requirements": [],
            "ready_to_plan": False,
        }

        for key, value in (
            defaults.items()
        ):

            if key in context:
                continue

            if isinstance(
                value,
                list,
            ):

                context[key] = list(
                    value
                )

            elif isinstance(
                value,
                dict,
            ):

                context[key] = dict(
                    value
                )

            else:

                context[key] = value

    # ========================================================
    # Framework
    # ========================================================

    def _detect_framework(
        self,
        text: str,
    ) -> Optional[str]:

        for framework, words in (
            self.FRAMEWORKS.items()
        ):

            if any(
                word in text
                for word in words
            ):

                return framework

        return None

    # ========================================================
    # Features
    # ========================================================

    def _detect_features(
        self,
        text: str,
    ) -> List[str]:

        lowered = text.lower()

        detected: List[str] = []

        for feature, words in (
            self.FEATURES.items()
        ):

            for word in words:

                if word not in lowered:
                    continue

                if self._is_negated(
                    lowered,
                    word,
                ):
                    continue

                if (
                    feature
                    not in detected
                ):

                    detected.append(
                        feature
                    )

                break

        return detected

    # ========================================================
    # Raw Features
    # ========================================================

    def _detect_raw_features(
        self,
        text: str,
    ) -> List[str]:

        lines = [
            line.strip()
            for line in text.splitlines()
        ]

        result: List[str] = []

        in_feature_section = False

        for line in lines:

            if not line:
                continue

            normalized = (
                line
                .replace("：", ":")
            )

            if any(
                key in normalized
                for key in (
                    "必要な機能",
                    "機能は以下",
                    "機能:",
                    "機能：",
                )
            ):

                in_feature_section = True
                continue

            if in_feature_section:

                if any(
                    key in normalized
                    for key in (
                        "画面は",
                        "画面:",
                        "画面：",
                        "デザイン",
                        "データベース",
                        "バックエンド",
                    )
                ):

                    in_feature_section = False
                    continue

                if re.match(
                    r"^\s*[-・*]\s*",
                    line,
                ):

                    item = re.sub(
                        r"^\s*[-・*]\s*",
                        "",
                        line,
                    ).strip()

                    if (
                        item
                        and not self._line_is_negated(
                            item
                        )
                        and item
                        not in result
                    ):

                        result.append(
                            item
                        )

        return result

    # ========================================================
    # Target
    # ========================================================

    def _detect_target(
        self,
        text: str,
    ) -> Optional[str]:

        explicit = re.search(
            r"(?:対象ユーザー|ターゲット|利用者)"
            r"\s*(?:は|:|：)?\s*"
            r"([^\n。]+)",
            text,
            flags=re.IGNORECASE,
        )

        if explicit:

            value = (
                explicit.group(1)
                .strip()
            )

            for candidate in (
                self.TARGET_USERS
            ):

                if candidate in value:
                    return candidate

            if value:
                return value[:60]

        for candidate in (
            self.TARGET_USERS
        ):

            if candidate in text:
                return candidate

        match = re.search(
            r"([^\n。、]{1,30})向け",
            text,
        )

        if match:

            value = (
                match.group(1)
                .strip()
            )

            if value:
                return value

        return None

    # ========================================================
    # Project Name
    # ========================================================

    def _detect_project_name(
        self,
        text: str,
    ) -> Optional[str]:

        patterns = (
            r"(?:プロジェクト名|アプリ名|名前)"
            r"\s*(?:は|:|：)?\s*"
            r"[「『\"]?([A-Za-z0-9_\-ぁ-んァ-ヶ一-龠]+)",

            r"(?:project name)"
            r"\s*(?:is|:)?\s*"
            r"[\"']?([A-Za-z0-9_\-]+)",
        )

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:

                value = (
                    match.group(1)
                    .strip()
                    .strip(
                        "」』\"'"
                    )
                )

                if value:
                    return value

        return None

    # ========================================================
    # Purpose
    # ========================================================

    def _detect_purpose(
        self,
        text: str,
    ) -> Optional[str]:

        # 明示形を最優先
        patterns = (
            r"(?:目的|用途)"
            r"\s*(?:は|:|：)?\s*"
            r"([^\n。]+)",

            r"(?:目的|用途)"
            r"\s*(?:は|:|：)?\s*"
            r"(.+?)(?:です|です。|\n|$)",
        )

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:

                value = (
                    match.group(1)
                    .strip()
                )

                value = re.sub(
                    r"^(?:、|,|\s)+",
                    "",
                    value,
                )

                if value:
                    return value[:160]

        purpose_patterns = (
            (
                "職業発見",
                (
                    "職業を発見",
                    "仕事を発見",
                    "職業発見",
                    "仕事を知る",
                    "職業を知る",
                ),
            ),
            (
                "学習支援",
                (
                    "学習支援",
                    "勉強を支援",
                    "学習を助け",
                    "勉強を助け",
                ),
            ),
            (
                "予定管理",
                (
                    "予定管理",
                    "スケジュール管理",
                    "予定を管理",
                ),
            ),
            (
                "情報共有",
                (
                    "情報共有",
                    "情報を共有",
                ),
            ),
        )

        lowered = text.lower()

        for purpose, keywords in (
            purpose_patterns
        ):

            if any(
                keyword in lowered
                for keyword in keywords
            ):

                return purpose

        # 「〜ため」「〜ようにする」
        match = re.search(
            r"([^。\n]{3,120}?)"
            r"(?:ため|ために|ようにすること)",
            text,
        )

        if match:

            value = (
                match.group(1)
                .strip()
            )

            if value:
                return value

        return None

    # ========================================================
    # Description
    # ========================================================

    def _detect_description(
        self,
        text: str,
        context: Dict[str, Any],
    ) -> Optional[str]:

        match = re.search(
            r"(?:概要|説明|description)"
            r"\s*(?:は|:|：)?\s*(.+)",
            text,
            flags=re.IGNORECASE,
        )

        if match:

            value = (
                match.group(1)
                .strip()
            )

            if value:
                return value

        if (
            "アプリ" in text
            and any(
                word in text
                for word in (
                    "作りたい",
                    "作って",
                    "開発したい",
                    "作成したい",
                )
            )
        ):

            existing = context.get(
                "description"
            )

            if not existing:

                first_paragraph = (
                    text.split(
                        "\n\n",
                        1,
                    )[0]
                    .strip()
                )

                return (
                    first_paragraph
                    or text[:300]
                )

        return None

    # ========================================================
    # Pages
    # ========================================================

    def _detect_pages(
        self,
        text: str,
    ) -> List[str]:

        lowered = text.lower()

        detected: List[str] = []

        for page, words in (
            self.PAGES.items()
        ):

            for word in words:

                if word not in lowered:
                    continue

                if self._is_negated(
                    lowered,
                    word,
                ):
                    continue

                if (
                    page
                    not in detected
                ):

                    detected.append(
                        page
                    )

                break

        return detected

    # ========================================================
    # Raw Pages
    # ========================================================

    def _detect_raw_pages(
        self,
        text: str,
    ) -> List[str]:

        lines = [
            line.strip()
            for line in text.splitlines()
        ]

        result: List[str] = []

        in_page_section = False

        for line in lines:

            if not line:
                continue

            if any(
                key in line
                for key in (
                    "画面は以下",
                    "画面:",
                    "画面：",
                    "必要な画面",
                )
            ):

                in_page_section = True
                continue

            if in_page_section:

                if any(
                    key in line
                    for key in (
                        "デザイン",
                        "データベース",
                        "バックエンド",
                        "制約",
                    )
                ):

                    in_page_section = False
                    continue

                if re.match(
                    r"^\s*[-・*]\s*",
                    line,
                ):

                    item = re.sub(
                        r"^\s*[-・*]\s*",
                        "",
                        line,
                    ).strip()

                    item = re.sub(
                        r"(画面|ページ)$",
                        "",
                        item,
                    ).strip()

                    if (
                        item
                        and item
                        not in result
                    ):

                        result.append(
                            item
                        )

        return result

    # ========================================================
    # Database
    # ========================================================

    def _detect_database(
        self,
        text: str,
    ) -> Optional[str]:

        lowered = text.lower()

        if self._contains_negative_keyword(
            lowered,
            (
                "データベース",
                "database",
                "db",
            ),
        ):

            return None

        for database, words in (
            self.DATABASES.items()
        ):

            if any(
                word in lowered
                for word in words
            ):

                return database

        return None

    # ========================================================
    # Backend
    # ========================================================

    def _detect_backend(
        self,
        text: str,
    ) -> Optional[str]:

        lowered = text.lower()

        if self._contains_negative_keyword(
            lowered,
            (
                "バックエンド",
                "backend",
            ),
        ):

            return None

        if any(
            keyword in lowered
            for keyword in (
                "フロントだけ",
                "フロントエンドだけ",
            )
        ):

            return None

        for backend, words in (
            self.BACKENDS.items()
        ):

            if any(
                word in lowered
                for word in words
            ):

                return backend

        return None

    # ========================================================
    # Design
    # ========================================================

    def _detect_design_preferences(
        self,
        text: str,
    ) -> List[str]:

        detected: List[str] = []

        for design, words in (
            self.DESIGN_PREFERENCES.items()
        ):

            if any(
                word in text
                for word in words
            ):

                detected.append(
                    design
                )

        return detected

    # ========================================================
    # Constraints
    # ========================================================

    def _detect_constraints(
        self,
        text: str,
    ) -> List[str]:

        detected: List[str] = []

        for constraint, words in (
            self.CONSTRAINTS.items()
        ):

            if any(
                word in text
                for word in words
            ):

                detected.append(
                    constraint
                )

        # 自然な「AやBは不要」にも対応
        if self._contains_negative_keyword(
            text,
            (
                "データベース",
                "database",
                "db",
            ),
        ):

            detected.append(
                "no_database"
            )

        if self._contains_negative_keyword(
            text,
            (
                "ログイン",
                "認証",
                "アカウント",
                "login",
            ),
        ):

            detected.append(
                "no_login"
            )

        return list(
            dict.fromkeys(
                detected
            )
        )

    # ========================================================
    # Apply Constraints
    # ========================================================

    def _apply_constraints(
        self,
        context: Dict[str, Any],
    ) -> None:

        constraints = set(
            context.get(
                "constraints",
                [],
            )
            or []
        )

        features = list(
            context.get(
                "features",
                [],
            )
            or []
        )

        if "no_database" in constraints:

            context[
                "database"
            ] = None

            features = [
                feature
                for feature in features
                if feature
                != "database"
            ]

        if "frontend_only" in constraints:

            context[
                "backend"
            ] = None

        if "no_login" in constraints:

            features = [
                feature
                for feature in features
                if feature
                != "authentication"
            ]

            pages = list(
                context.get(
                    "pages",
                    [],
                )
                or []
            )

            context[
                "pages"
            ] = [
                page
                for page in pages
                if page
                not in (
                    "login",
                    "signup",
                )
            ]

        context[
            "features"
        ] = features

    # ========================================================
    # Completeness
    # ========================================================

    def _update_completeness(
        self,
        context: Dict[str, Any],
    ) -> None:
        """ProjectPlannerへ進める状態か判定する。"""

        if not str(context.get("target_user") or "").strip():
            context["target_user"] = "お菓子のパッケージをデザインしたい一般ユーザー"

        if not str(context.get("purpose") or "").strip():
            context["purpose"] = str(
                context.get("description")
                or "ユーザーの要件を満たすアプリを生成する"
            ).strip()

        # target_userやpurposeは補完できるので、生成停止条件にしない
        required_fields = (
            "project_name",
            "framework",
        )

        missing = [
            field
            for field in required_fields
            if not context.get(field)
        ]

        context["missing_requirements"] = missing
        context["ready_to_plan"] = not missing
    # ========================================================
    # Negation helpers
    # ========================================================

    def _is_negated(
        self,
        text: str,
        keyword: str,
    ) -> bool:

        start = text.find(
            keyword
        )

        if start < 0:
            return False

        left = max(
            0,
            start - 24,
        )

        right = min(
            len(text),
            start
            + len(keyword)
            + 24,
        )

        window = text[
            left:right
        ]

        return any(
            negation in window
            for negation in self.NEGATION_WORDS
        )

    def _contains_negative_keyword(
        self,
        text: str,
        keywords: Tuple[
            str,
            ...
        ],
    ) -> bool:

        for keyword in keywords:

            search_from = 0

            while True:

                start = text.find(
                    keyword,
                    search_from,
                )

                if start < 0:
                    break

                left = max(
                    0,
                    start - 16,
                )

                right = min(
                    len(text),
                    start
                    + len(keyword)
                    + 32,
                )

                window = text[
                    left:right
                ]

                if any(
                    negation in window
                    for negation
                    in self.NEGATION_WORDS
                ):

                    return True

                search_from = (
                    start
                    + len(keyword)
                )

        return False

    def _line_is_negated(
        self,
        line: str,
    ) -> bool:

        lowered = (
            line.lower()
        )

        return any(
            negation in lowered
            for negation
            in self.NEGATION_WORDS
        )

    # ========================================================
    # Utility
    # ========================================================

    @staticmethod
    def _merge_list(
        current: Any,
        incoming: Any,
    ) -> List[Any]:

        result: List[Any] = []

        if isinstance(
            current,
            list,
        ):

            for item in current:

                if item not in result:

                    result.append(
                        item
                    )

        if isinstance(
            incoming,
            list,
        ):

            for item in incoming:

                if item not in result:

                    result.append(
                        item
                    )

        return result


# ============================================================
# Standalone Test
# ============================================================

if __name__ == "__main__":

    analyzer = (
        RequirementAnalyzer()
    )

    message = """
Reactで読書記録アプリを作ってください。

プロジェクト名は reading-log-app です。

目的は、読んだ本を記録して後から振り返れるようにすることです。
対象ユーザーは中学生です。

必要な機能は以下です。
- 本のタイトルを登録する
- 著者名を登録する
- 読み終わった本を完了状態にする
- お気に入り登録する
- 登録した本を一覧表示する
- タイトルで検索する

画面は以下の3つにしてください。
- ホーム画面
- 本の一覧画面
- 本の詳細画面

デザインはシンプルで、スマートフォンでも見やすくしてください。
データベースやログイン機能は今回は不要です。

この内容でプロジェクトを生成してください。
""".strip()

    result = analyzer.analyze(
        message
    )

    import json

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
