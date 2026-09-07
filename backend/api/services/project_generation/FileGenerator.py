"""Generate project files from a validated BuildPlan, one file at a time."""

from __future__ import annotations

import html
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .BuildPlan import BuildFile, BuildPlan


@dataclass
class GeneratedFile:
    """In-memory file passed from FileGenerator to FileWriter."""

    path: str
    content: str
    status: str = "success"
    source: str = "local_llm"
    error: Optional[str] = None

    def __post_init__(self) -> None:
        self.path = BuildFile.normalize_path(self.path)
        self.content = str(self.content or "")
        self.status = str(self.status or "error").strip().lower()
        self.source = str(self.source or "unknown").strip().lower()
        self.error = str(self.error).strip() if self.error else None
        if self.status not in {"success", "error"}:
            self.status = "error"
            self.error = self.error or "未対応の生成ステータスです。"
        if self.status == "success" and not self.content.strip():
            self.status = "error"
            self.error = self.error or "生成されたファイルが空です。"

    @property
    def success(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "status": self.status,
            "source": self.source,
            "error": self.error,
        }


class FileGenerator:
    """Generate every BuildFile while limiting each LLM call to one file.

    Known framework files use deterministic templates. Files without a safe
    template use the optional LLM. A failure is isolated to its GeneratedFile,
    allowing ProjectBuildService to decide whether partial output may proceed.
    """

    MAX_GENERATED_CHARS = 500_000
    MAX_CONTEXT_CHARS = 8_000
    MAX_CONTEXT_FILES = 6
    MAX_CONTEXT_FILE_CHARS = 2_500

    _FENCE_START = re.compile(r"^\s*```[a-zA-Z0-9_+\-#.]*\s*\n?")
    _FENCE_END = re.compile(r"\n?\s*```\s*$")
    _SAFE_PACKAGE = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$")

    def __init__(
        self,
        llm_engine: Optional[Any] = None,
        enable_debug: bool = False,
        max_llm_attempts: int = 2,
    ) -> None:
        self.llm_engine = llm_engine
        self.enable_debug = bool(enable_debug)
        self.max_llm_attempts = max(1, min(int(max_llm_attempts), 3))
        self.last_diagnostics: List[str] = []

    def generate_project(
        self,
        plan: BuildPlan,
        project_context: Optional[Dict[str, Any]] = None,
        use_ai: bool = True,
    ) -> List[GeneratedFile]:
        """Generate a project in dependency-aware order."""
        if not isinstance(plan, BuildPlan):
            raise TypeError("plan must be a BuildPlan")
        plan.validate_or_raise()
        context = dict(project_context or {})
        generated: Dict[str, GeneratedFile] = {}
        self.last_diagnostics = []

        for file_spec in self._generation_order(plan.files):
            generated[file_spec.path] = self.generate_file(
                plan=plan,
                file_spec=file_spec,
                project_context=context,
                generated_files=generated,
                use_ai=use_ai,
            )
        return list(generated.values())

    def generate_file(
        self,
        plan: BuildPlan,
        file_spec: BuildFile,
        project_context: Optional[Dict[str, Any]] = None,
        generated_files: Optional[Dict[str, GeneratedFile]] = None,
        use_ai: bool = True,
    ) -> GeneratedFile:
        """Generate one file without allowing failure to abort sibling files."""
        if not isinstance(file_spec, BuildFile) or not file_spec.is_valid():
            return self._failure(
                getattr(file_spec, "path", ""),
                "invalid_spec",
                "生成対象のファイル定義が不正です。",
            )

        context = dict(project_context or {})
        deterministic = self._generate_deterministic(plan, file_spec, context)

        # package.jsonやtsconfigなど、構文が固定的な基盤ファイルは
        # LLMよりテンプレートを優先する。
        if deterministic is not None and self._prefer_template(file_spec.path):
            return GeneratedFile(
                path=file_spec.path,
                content=self._ensure_final_newline(deterministic),
                source="template",
            )

        if use_ai and self._llm_available():
            generated = self._generate_with_llm(
                plan=plan,
                file_spec=file_spec,
                project_context=context,
                generated_files=generated_files or {},
            )
            if generated.success:
                return generated
            self._debug(
                f"LLM failed; deterministic fallback will be used: {file_spec.path}"
            )

        # Ollama停止中やファイル単位のLLM失敗時も、既知形式なら
        # プロジェクト全体を中断せず安全なテンプレートへ退避する。
        if deterministic is not None:
            return GeneratedFile(
                path=file_spec.path,
                content=self._ensure_final_newline(deterministic),
                source="template_fallback" if use_ai else "template",
            )

        reason = (
            "AI生成が無効で、このファイルに対応するテンプレートがありません。"
            if not use_ai
            else "LocalLLMが利用できず、このファイルに対応するテンプレートがありません。"
        )
        return self._failure(file_spec.path, "none", reason)

    def _generate_with_llm(
        self,
        *,
        plan: BuildPlan,
        file_spec: BuildFile,
        project_context: Dict[str, Any],
        generated_files: Dict[str, GeneratedFile],
    ) -> GeneratedFile:
        messages = self._build_file_messages(
            plan=plan,
            file_spec=file_spec,
            project_context=project_context,
            generated_files=generated_files,
        )
        last_error = "LocalLLMによる生成に失敗しました。"

        for attempt in range(1, self.max_llm_attempts + 1):
            try:
                result = self._call_llm(messages)
                if inspect.isawaitable(result):
                    self._close_awaitable(result)
                    last_error = "同期生成中に非同期LLMが返されました。"
                    break

                text, error = self._extract_llm_result(result)
                if error:
                    last_error = error
                    continue

                content = self._clean_generated_content(text, file_spec)
                if not content:
                    last_error = "LocalLLMが空のファイルを返しました。"
                    continue
                if len(content) > self.MAX_GENERATED_CHARS:
                    last_error = "生成内容が許容サイズを超えました。"
                    continue

                return GeneratedFile(
                    path=file_spec.path,
                    content=self._ensure_final_newline(content),
                    source="local_llm",
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._debug(
                    f"LLM attempt {attempt}/{self.max_llm_attempts} failed "
                    f"for {file_spec.path}: {last_error}"
                )

        return self._failure(file_spec.path, "local_llm", last_error)

    @staticmethod
    def _prefer_template(path: str) -> bool:
        normalized = BuildFile.normalize_path(path).casefold()
        name = PurePosixPath(normalized).name
        return normalized in {
            "package.json",
            "index.html",
            "vite.config.js",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.app.json",
            "tsconfig.node.json",
            "src/main.jsx",
            "src/main.tsx",
            "src/vite-env.d.ts",
            "tests/setup.js",
            "tests/setup.ts",
            "src/test/setup.js",
            "src/test/setup.ts",
        } or name in {".gitignore", ".env.example"}

    def _llm_available(self) -> bool:
        if self.llm_engine is None:
            return False
        value = getattr(self.llm_engine, "is_available", True)
        try:
            result = value() if callable(value) else value
            if inspect.isawaitable(result):
                self._close_awaitable(result)
                return False
            return bool(result)
        except Exception as exc:
            self._debug(f"LLM availability check failed: {exc}")
            return False

    def _call_llm(self, messages: List[Dict[str, str]]) -> Any:
        assert self.llm_engine is not None
        chat = getattr(self.llm_engine, "chat", None)
        if callable(chat):
            return chat(messages, temperature=0.2, max_tokens=2600)
        generate = getattr(self.llm_engine, "generate", None)
        if callable(generate):
            return generate(messages)
        raise TypeError("LLM engine must provide chat() or generate()")

    @staticmethod
    def _extract_llm_result(result: Any) -> tuple[str, Optional[str]]:
        if isinstance(result, str):
            return result, None
        if isinstance(result, Mapping):
            if result.get("success") is False:
                return "", str(result.get("error") or "LocalLLMが生成に失敗しました。")
            return str(result.get("text") or result.get("content") or ""), None
        if getattr(result, "success", True) is False:
            return "", str(getattr(result, "error", None) or "LocalLLMが生成に失敗しました。")
        return str(
            getattr(result, "text", None) or getattr(result, "content", None) or ""
        ), None

    def _build_file_messages(
        self,
        plan: BuildPlan,
        file_spec: BuildFile,
        project_context: Dict[str, Any],
        generated_files: Dict[str, GeneratedFile],
    ) -> List[Dict[str, str]]:
        system = """あなたはアプリケーション開発を担当するシニアエンジニアです。
指定された1ファイルだけを生成してください。

【厳守事項】
- 回答には完成したファイル内容だけを出力する。
- Markdownコードブロック、挨拶、解説を出力しない。
- 指定されていないファイルを生成しない。
- BuildPlanにないライブラリや相対importを勝手に追加しない。
- TODOや空の仮実装だけで終わらせない。
- JSONは有効なJSON、JSXは有効な構文にする。
- ユーザー要件と既存ファイルとの整合性を優先する。"""
        project = {
            "project_name": plan.project_name,
            "description": plan.description,
            "framework": plan.framework,
            "features": plan.features,
            "pages": plan.pages,
            "target_user": plan.target_user,
            "purpose": plan.purpose,
            "database": plan.database,
            "backend": plan.backend,
            "design_preferences": plan.design_preferences,
            "constraints": plan.constraints,
            "dependencies": plan.dependencies,
            "dev_dependencies": plan.dev_dependencies,
        }
        target = file_spec.to_dict()
        related = self._build_existing_file_context(
            generated_files, related_paths=file_spec.dependencies
        )
        user = (
            "【プロジェクト】\n"
            + json.dumps(project, ensure_ascii=False, indent=2, default=str)
            + "\n\n【追加要件】\n"
            + json.dumps(project_context, ensure_ascii=False, indent=2, default=str)
            + "\n\n【全ファイル構成】\n"
            + json.dumps([item.to_dict() for item in plan.files], ensure_ascii=False, indent=2)
            + "\n\n【今回の対象ファイル】\n"
            + json.dumps(target, ensure_ascii=False, indent=2)
            + "\n\n【生成済みの関連ファイル】\n"
            + related
            + f"\n\n{file_spec.path} の内容だけを出力してください。"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _build_existing_file_context(
        self,
        generated_files: Mapping[str, GeneratedFile],
        related_paths: Optional[Sequence[str]] = None,
    ) -> str:
        if not generated_files:
            return "まだ生成済みファイルはありません。"
        preferred = [path for path in (related_paths or []) if path in generated_files]
        recent = list(generated_files.keys())[-self.MAX_CONTEXT_FILES :]
        paths = self._unique(preferred + recent)
        chunks: List[str] = []
        total = 0
        for path in paths:
            generated = generated_files[path]
            if not generated.success:
                continue
            preview = generated.content[: self.MAX_CONTEXT_FILE_CHARS]
            chunk = f"--- {path} ---\n{preview.rstrip()}\n"
            if total + len(chunk) > self.MAX_CONTEXT_CHARS:
                break
            chunks.append(chunk)
            total += len(chunk)
        return "\n".join(chunks) if chunks else "なし"

    def _generate_deterministic(
        self,
        plan: BuildPlan,
        file_spec: BuildFile,
        project_context: Dict[str, Any],
    ) -> Optional[str]:
        path = file_spec.path.casefold()
        suffix = PurePosixPath(path).suffix
        framework = str(plan.framework or "").strip().lower()

        if path == "readme.md":
            return self._readme(plan)
        if PurePosixPath(path).name == ".gitignore":
            return self._gitignore()
        if PurePosixPath(path).name == ".env.example":
            return "VITE_API_BASE_URL=http://localhost:8000\n"

        if framework in {"react", "react-ts", "react_typescript", "vite-react"}:
            templates = {
                "package.json": lambda: self._package_json(plan, "react"),
                "index.html": lambda: self._react_index_html(plan),
                "src/main.jsx": self._react_main_jsx,
                "src/app.jsx": lambda: self._react_app_jsx(plan),
                "src/main.tsx": self._react_main_tsx,
                "src/app.tsx": lambda: self._react_app_tsx(plan),
                "src/index.css": lambda: self._base_css(plan),
                "src/app.css": lambda: self._feature_css(file_spec),
                "vite.config.js": lambda: self._vite_config(False),
                "vite.config.ts": lambda: self._vite_config(True),
                "tsconfig.json": self._tsconfig,
                "tsconfig.app.json": self._tsconfig_app,
                "tsconfig.node.json": self._tsconfig_node,
                "src/vite-env.d.ts": lambda: '/// <reference types="vite/client" />\n',
                "tests/setup.js": self._test_setup,
                "tests/setup.ts": self._test_setup,
                "src/test/setup.js": self._test_setup,
                "src/test/setup.ts": self._test_setup,
            }
            if path in templates:
                return templates[path]()
            if path.startswith(("src/components/", "src/pages/")) and suffix in {
                ".jsx",
                ".tsx",
            }:
                return self._react_component(file_spec, typescript=suffix == ".tsx")
            if path.startswith("src/hooks/"):
                return self._react_hook(file_spec, typescript=suffix == ".ts")
            if path.startswith("src/services/"):
                return self._react_service(file_spec, typescript=suffix == ".ts")
            if path.startswith("src/utils/"):
                return self._javascript_utility(file_spec, typescript=suffix == ".ts")
            if path.startswith("src/data/"):
                return self._javascript_data(file_spec, typescript=suffix == ".ts")
            if path.startswith(("src/types/", "src/models/")) and suffix in {
                ".ts",
                ".tsx",
            }:
                return self._typescript_types(file_spec, project_context)
            if path.startswith("src/styles/"):
                return self._feature_css(file_spec)
            if "test" in path and suffix in {".js", ".jsx", ".ts", ".tsx"}:
                return self._javascript_test(file_spec, typescript=suffix in {".ts", ".tsx"})
            if suffix == ".css":
                return self._feature_css(file_spec)
            if suffix == ".json":
                return "{}\n"

        if framework in {"nextjs", "next.js", "next"}:
            templates = {
                "package.json": lambda: self._package_json(plan, "nextjs"),
                "app/layout.jsx": lambda: self._next_layout(plan),
                "app/page.jsx": lambda: self._next_page(plan),
                "app/globals.css": lambda: self._base_css(plan),
            }
            if path in templates:
                return templates[path]()

        if framework in {"html", "vanilla", "vanilla-js"}:
            templates = {
                "index.html": lambda: self._html_index(plan),
                "style.css": lambda: self._base_css(plan),
                "script.js": lambda: self._html_script(plan),
            }
            if path in templates:
                return templates[path]()
        return None

    def _package_json(self, plan: BuildPlan, framework: str) -> str:
        if framework == "react":
            dependency_defaults = {"react": "^18.3.1", "react-dom": "^18.3.1"}
            dev_defaults = {
                "vite": "^5.4.0",
                "@vitejs/plugin-react": "^4.3.1",
                "typescript": "^5.6.2",
                "vitest": "^2.1.1",
                "jsdom": "^25.0.1",
                "@testing-library/react": "^16.1.0",
                "@testing-library/jest-dom": "^6.6.3",
                "@types/react": "^18.3.3",
                "@types/react-dom": "^18.3.0",
            }
        else:
            dependency_defaults = {
                "next": "^14.2.15",
                "react": "^18.3.1",
                "react-dom": "^18.3.1",
            }
            dev_defaults = {}
        dependencies = self._package_map(plan.dependencies, dependency_defaults)
        dev_dependencies = self._package_map(plan.dev_dependencies, dev_defaults)
        scripts = dict(plan.scripts or {})
        if framework == "react":
            scripts.setdefault("dev", "vite")
            scripts.setdefault("build", "tsc --noEmit && vite build")
            scripts.setdefault("preview", "vite preview")
            scripts.setdefault("test", "vitest run")
            scripts.setdefault("test:watch", "vitest")

        payload: Dict[str, Any] = {
            "name": plan.project_name,
            "private": True,
            "version": "0.1.0",
            "scripts": scripts,
            "dependencies": dependencies,
        }
        if framework == "react":
            payload["type"] = "module"
        if dev_dependencies:
            payload["devDependencies"] = dev_dependencies
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _package_map(
        self, packages: Iterable[str], defaults: Mapping[str, str]
    ) -> Dict[str, str]:
        result = dict(defaults)
        for raw in packages:
            name, version = self._split_package_spec(str(raw).strip())
            if name and self._SAFE_PACKAGE.fullmatch(name):
                result.setdefault(name, version or "latest")
        return result

    @staticmethod
    def _split_package_spec(spec: str) -> tuple[str, Optional[str]]:
        if spec.startswith("@"):
            separator = spec.rfind("@")
            if separator > spec.find("/"):
                return spec[:separator], spec[separator + 1 :] or None
            return spec, None
        if "@" in spec:
            name, version = spec.rsplit("@", 1)
            return name, version or None
        return spec, None

    @staticmethod
    def _react_main_jsx() -> str:
        return """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
"""

    @staticmethod
    def _react_main_tsx() -> str:
        return """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('root element was not found');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
"""

    @staticmethod
    def _vite_config(typescript: bool) -> str:
        del typescript
        return """import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
});
"""

    @staticmethod
    def _tsconfig() -> str:
        return """{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
"""

    @staticmethod
    def _tsconfig_app() -> str:
        return """{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "composite": true,
    "noEmit": true
  },
  "include": ["src"]
}
"""

    @staticmethod
    def _tsconfig_node() -> str:
        return """{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "allowImportingTsExtensions": true
  },
  "include": ["vite.config.ts"]
}
"""

    def _react_index_html(self, plan: BuildPlan) -> str:
        title = html.escape(plan.project_name or "React App")
        return f"""<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

    def _react_app_jsx(self, plan: BuildPlan) -> str:
        children = [
            item for item in plan.files if item.path.startswith(("src/components/", "src/pages/"))
        ]
        imports: List[str] = []
        elements: List[str] = []
        used: set[str] = set()
        for item in children:
            name = self._component_name(item.path, used)
            relative = "./" + item.path.removeprefix("src/")
            imports.append(f"import {name} from '{relative}';")
            elements.append(f"      <{name} />")
        imports_text = "\n".join(imports)
        elements_text = "\n".join(elements) or "      <p>要件をもとにアプリを生成しました。</p>"
        description = html.escape(plan.description or plan.purpose or "Generated application")
        return f"""{imports_text}{chr(10) if imports_text else ''}export default function App() {{
  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">{html.escape(plan.framework.upper())}</p>
        <h1>{html.escape(plan.project_name)}</h1>
        <p>{description}</p>
      </header>
      <section className="content-grid">
{elements_text}
      </section>
    </main>
  );
}}
"""

    def _react_app_tsx(self, plan: BuildPlan) -> str:
        children = [
            item
            for item in plan.files
            if item.path.casefold().startswith(("src/components/", "src/pages/"))
            and item.path.casefold().endswith(".tsx")
            and ".test." not in item.path.casefold()
            and ".spec." not in item.path.casefold()
        ]
        imports: List[str] = []
        elements: List[str] = []
        used: set[str] = set()
        for item in children:
            name = self._component_name(item.path, used)
            relative = "./" + item.path.removeprefix("src/")
            relative = re.sub(r"\.tsx$", "", relative, flags=re.IGNORECASE)
            imports.append(f"import {name} from '{relative}';")
            elements.append(f"        <{name} />")

        imports_text = "\n".join(imports)
        elements_text = "\n".join(elements) or "        <p>要件をもとにアプリを生成しました。</p>"
        title = json.dumps(plan.project_name, ensure_ascii=False)
        description = json.dumps(
            plan.description or plan.purpose or "Generated application",
            ensure_ascii=False,
        )
        return f"""{imports_text}{chr(10) if imports_text else ''}export default function App() {{
  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">REACT + TYPESCRIPT</p>
        <h1>{{{title}}}</h1>
        <p>{{{description}}}</p>
      </header>
      <section className="content-grid" aria-label="アプリケーション機能">
{elements_text}
      </section>
    </main>
  );
}}
"""

    def _react_component(
        self,
        file_spec: BuildFile,
        *,
        typescript: bool = False,
    ) -> str:
        name = self._component_name(file_spec.path)
        description = file_spec.description or f"{name} component"
        if name == "SearchBar":
            event_type = ": React.ChangeEvent<HTMLInputElement>" if typescript else ""
            react_import = "import type React from 'react';\n\n" if typescript else ""
            return f"""{react_import}export default function SearchBar() {{
  const handleChange = (event{event_type}) => {{
    void event.currentTarget.value;
  }};

  return (
    <label className="card">
      <span>検索</span>
      <input type="search" placeholder="キーワードを入力" onChange={{handleChange}} />
    </label>
  );
}}
"""
        if name == "FavoriteButton":
            return """import { useState } from 'react';

export default function FavoriteButton() {
  const [favorite, setFavorite] = useState(false);
  return (
    <button type="button" onClick={() => setFavorite((value) => !value)}>
      {favorite ? '★ お気に入り済み' : '☆ お気に入りに追加'}
    </button>
  );
}
"""
        safe_description = html.escape(description)
        return f"""export default function {name}() {{
  return (
    <section className="card" aria-labelledby="{name}-title">
      <h2 id="{name}-title">{html.escape(self._humanize_name(name))}</h2>
      <p>{safe_description}</p>
    </section>
  );
}}
"""

    def _react_hook(self, file_spec: BuildFile, *, typescript: bool = False) -> str:
        """Generate a deterministic React hook for a file under src/hooks."""
        name = self._component_name(file_spec.path)
        hook_name = name if name.startswith("use") else f"use{name}"
        generic = "<T>" if typescript else ""
        initial_type = ": T" if typescript else ""
        return_type_value = "useState<T>(initialValue)" if typescript else "useState(initialValue)"
        return f"""import {{ useCallback, useState }} from 'react';

export function {hook_name}{generic}(initialValue{initial_type}) {{
  const [value, setValue] = {return_type_value};

  const reset = useCallback(() => setValue(initialValue), [initialValue]);

  return {{ value, setValue, reset }};
}}

export default {hook_name};
"""

    def _react_service(self, file_spec: BuildFile, *, typescript: bool = False) -> str:
        """Generate a small, usable service with safe localStorage persistence."""
        stem = PurePosixPath(file_spec.path).stem
        storage_key = re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-")
        storage_key = storage_key or "generated-items"
        type_decl = "<T>" if typescript else ""
        return_type = ": T[]" if typescript else ""
        item_type = ": T[]" if typescript else ""
        fallback_type = ": T[]" if typescript else ""
        return f"""const STORAGE_KEY = '{storage_key}';

export function loadItems{type_decl}(fallback{fallback_type} = []){return_type} {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : fallback;
  }} catch {{
    return fallback;
  }}
}}

export function saveItems{type_decl}(items{item_type}): void {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}}

export function clearItems(): void {{
  localStorage.removeItem(STORAGE_KEY);
}}
""" if typescript else f"""const STORAGE_KEY = '{storage_key}';

export function loadItems(fallback = []) {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : fallback;
  }} catch {{
    return fallback;
  }}
}}

export function saveItems(items) {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}}

export function clearItems() {{
  localStorage.removeItem(STORAGE_KEY);
}}
"""

    def _javascript_utility(
        self,
        file_spec: BuildFile,
        *,
        typescript: bool = False,
    ) -> str:
        stem = PurePosixPath(file_spec.path).stem.casefold()
        if any(word in stem for word in ("valid", "sanitize", "guard")):
            if typescript:
                return """export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export function validateRequired(
  values: Record<string, unknown>,
  requiredKeys: string[],
): ValidationResult {
  const errors = requiredKeys
    .filter((key) => values[key] === undefined || values[key] === null || values[key] === '')
    .map((key) => `${key} は必須です。`);

  return { valid: errors.length === 0, errors };
}
"""
            return """export function validateRequired(values, requiredKeys) {
  const errors = requiredKeys
    .filter((key) => values[key] === undefined || values[key] === null || values[key] === '')
    .map((key) => `${key} は必須です。`);

  return { valid: errors.length === 0, errors };
}
"""

        type_annotation = ": string" if typescript else ""
        return f"""export function createId(){type_annotation} {{
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {{
    return crypto.randomUUID();
  }}
  return `${{Date.now()}}-${{Math.random().toString(16).slice(2)}}`;
}}

export function formatDate(value{': string | number | Date' if typescript else ''}){type_annotation} {{
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('ja-JP');
}}
"""

    def _javascript_data(
        self,
        file_spec: BuildFile,
        *,
        typescript: bool = False,
    ) -> str:
        name = self._component_name(file_spec.path)
        declaration = f"export const {name}: readonly unknown[]" if typescript else f"export const {name}"
        return f"""{declaration} = [
  {{ id: 'sample-1', title: 'サンプル1', createdAt: '2026-01-01T00:00:00.000Z' }},
  {{ id: 'sample-2', title: 'サンプル2', createdAt: '2026-01-02T00:00:00.000Z' }},
];
"""

    def _typescript_types(
        self,
        file_spec: BuildFile,
        project_context: Mapping[str, Any],
    ) -> str:
        raw_entity = (
            project_context.get("entity_name")
            or project_context.get("model_name")
            or PurePosixPath(file_spec.path).stem
            or "GeneratedItem"
        )
        entity = self._component_name(str(raw_entity))
        if entity.lower() in {"type", "types", "index", "model", "models"}:
            entity = "GeneratedItem"
        return f"""export type EntityId = string;

export interface {entity} {{
  id: EntityId;
  title: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
}}

export type {entity}Input = Omit<{entity}, 'id' | 'createdAt' | 'updatedAt'>;

export interface HistoryEntry<T> {{
  id: EntityId;
  action: 'create' | 'update' | 'delete';
  snapshot: T;
  occurredAt: string;
}}
"""

    def _feature_css(self, file_spec: BuildFile) -> str:
        name = PurePosixPath(file_spec.path).stem
        selector = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "feature"
        return f""".{selector} {{
  display: grid;
  gap: 1rem;
}}

.{selector}__header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}}

@media (max-width: 640px) {{
  .{selector}__header {{
    align-items: stretch;
    flex-direction: column;
  }}
}}
"""

    def _javascript_test(
        self,
        file_spec: BuildFile,
        *,
        typescript: bool = False,
    ) -> str:
        del file_spec, typescript
        return """import { describe, expect, it } from 'vitest';

describe('generated project', () => {
  it('has a working test environment', () => {
    expect(true).toBe(true);
  });
});
"""

    @staticmethod
    def _test_setup() -> str:
        return """import '@testing-library/jest-dom';
"""

    @staticmethod
    def _gitignore() -> str:
        return """node_modules/
dist/
coverage/
.env
.env.local
*.log
.DS_Store
"""

    def _next_layout(self, plan: BuildPlan) -> str:
        return f"""import './globals.css';

export const metadata = {{
  title: {json.dumps(plan.project_name, ensure_ascii=False)},
  description: {json.dumps(plan.description or 'Generated application', ensure_ascii=False)},
}};

export default function RootLayout({{ children }}) {{
  return (
    <html lang="ja">
      <body>{{children}}</body>
    </html>
  );
}}
"""

    def _next_page(self, plan: BuildPlan) -> str:
        return f"""export default function Home() {{
  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">NEXT.JS</p>
        <h1>{html.escape(plan.project_name)}</h1>
        <p>{html.escape(plan.description or plan.purpose or 'Generated application')}</p>
      </section>
    </main>
  );
}}
"""

    def _html_index(self, plan: BuildPlan) -> str:
        return f"""<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{html.escape(plan.project_name)}</title>
    <link rel="stylesheet" href="style.css" />
  </head>
  <body>
    <main class="app-shell">
      <section class="hero">
        <p class="eyebrow">HTML</p>
        <h1>{html.escape(plan.project_name)}</h1>
        <p>{html.escape(plan.description or plan.purpose or 'Generated application')}</p>
        <button id="start-button" type="button">はじめる</button>
      </section>
    </main>
    <script src="script.js"></script>
  </body>
</html>
"""

    @staticmethod
    def _html_script(plan: BuildPlan) -> str:
        del plan
        return """const startButton = document.querySelector('#start-button');

startButton?.addEventListener('click', () => {
  startButton.textContent = '準備できました';
  startButton.setAttribute('aria-pressed', 'true');
});
"""

    @staticmethod
    def _base_css(plan: BuildPlan) -> str:
        del plan
        return """:root {
  color: #172033;
  background: #f4f7fb;
  font-family: Inter, "Noto Sans JP", system-ui, sans-serif;
  font-synthesis: none;
}

* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; min-height: 100vh; }
button, input { font: inherit; }
.app-shell { width: min(1080px, calc(100% - 32px)); margin: 0 auto; padding: 64px 0; }
.hero, .card { background: #fff; border: 1px solid #dfe6f0; border-radius: 20px; padding: 24px; box-shadow: 0 16px 40px rgba(34, 52, 84, 0.08); }
.hero { margin-bottom: 24px; }
.eyebrow { color: #526fe8; font-size: 0.78rem; font-weight: 800; letter-spacing: 0.12em; }
.content-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
input { width: 100%; margin-top: 8px; padding: 12px; border: 1px solid #bac6d8; border-radius: 10px; }
button { padding: 10px 16px; border: 0; border-radius: 10px; color: #fff; background: #526fe8; cursor: pointer; }
@media (max-width: 640px) { .app-shell { padding: 24px 0; } }
"""

    def _readme(self, plan: BuildPlan) -> str:
        features = "\n".join(f"- {item}" for item in plan.features) or "- 未設定"
        if plan.framework == "html":
            development = "`index.html`をブラウザで開いてください。"
        else:
            development = "```bash\nnpm install\nnpm run dev\n```"
        return f"""# {plan.project_name}

{plan.description or 'Generated application'}

## Framework

{plan.framework}

## Features

{features}

## Development

{development}
"""

    def _clean_generated_content(self, content: Any, file_spec: BuildFile) -> str:
        del file_spec
        cleaned = str(content or "").strip().lstrip("\ufeff")
        cleaned = self._FENCE_START.sub("", cleaned, count=1)
        cleaned = self._FENCE_END.sub("", cleaned, count=1)
        return cleaned.strip()

    @staticmethod
    def _generation_order(files: Sequence[BuildFile]) -> List[BuildFile]:
        by_path = {item.path.casefold(): item for item in files}
        ordered: List[BuildFile] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(item: BuildFile) -> None:
            key = item.path.casefold()
            if key in visited:
                return
            if key in visiting:
                return
            visiting.add(key)
            for dependency in item.dependencies:
                target = by_path.get(dependency.casefold())
                if target:
                    visit(target)
            visiting.remove(key)
            visited.add(key)
            ordered.append(item)

        for file_spec in files:
            visit(file_spec)
        return ordered

    @staticmethod
    def _component_name(path: str, used: Optional[set[str]] = None) -> str:
        stem = PurePosixPath(path).stem
        words = re.findall(r"[a-zA-Z0-9]+", stem)
        name = "".join(word[:1].upper() + word[1:] for word in words) or "GeneratedView"
        if name[:1].isdigit():
            name = "View" + name
        if used is not None:
            base = name
            suffix = 2
            while name in used:
                name = f"{base}{suffix}"
                suffix += 1
            used.add(name)
        return name

    @staticmethod
    def _humanize_name(name: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", " ", name)

    @staticmethod
    def _unique(values: Sequence[str]) -> List[str]:
        result: List[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.casefold()
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result

    @staticmethod
    def _ensure_final_newline(content: str) -> str:
        return content.rstrip() + "\n"

    @staticmethod
    def _close_awaitable(value: Any) -> None:
        close = getattr(value, "close", None)
        if callable(close):
            close()

    def _failure(self, path: str, source: str, error: str) -> GeneratedFile:
        self._debug(f"generation failed for {path}: {error}")
        return GeneratedFile(path=path, content="", status="error", source=source, error=error)

    def _debug(self, message: str) -> None:
        self.last_diagnostics.append(message)
        if self.enable_debug:
            print(f"[FileGenerator] {message}", flush=True)


__all__ = ["FileGenerator", "GeneratedFile"]
