# KnowledgeManager.py→ContextManager.py

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# -------------------------------------------------------------------
# 1. 各層（Layer）のデータ構造定義
# -------------------------------------------------------------------

@dataclass
class RoutingState:
    """Inspector が判定した現在のモードや意図を保持する層"""
    current_mode: str = "unknown"
    active_targets: List[str] = field(default_factory=list)
    last_intent_score: int = 0
    forced_handler: Optional[str] = None

@dataclass
class Workspace:
    """現在生成・編集中の成果物（コードやデータ）を保持する層"""
    current_code: Optional[str] = None
    current_json: Optional[Dict[str, Any]] = None
    version: int = 1
    active_artifact_name: Optional[str] = None

@dataclass
class Message:
    """チャット履歴の1単位"""
    role: str  # "user", "assistant", "system"
    content: str

@dataclass
class MemoryLayer:
    """LLMとの会話履歴と、必要に応じた要約を保持する層"""
    history: List[Message] = field(default_factory=list)
    summary: Optional[str] = None
    max_history_length: int = 10  # 直近N回のやり取りのみ保持（トークン節約）

    def add_message(self, role: str, content: str):
        self.history.append(Message(role=role, content=content))
        # 最大保持数を超えたら古いものから削除（FIFO）
        if len(self.history) > self.max_history_length:
            self.history = self.history[-self.max_history_length:]

@dataclass
class UserPreferences:
    """ユーザーが指定した不変の好みやプロジェクト全体の設定を保持する層"""
    global_theme: Optional[str] = None
    surface_preference: Optional[str] = None
    is_responsive_default: bool = False


# -------------------------------------------------------------------
# 2. ContextManager 本体
# -------------------------------------------------------------------

class ContextManager:
    """
    アプリケーション全体の状態（Context）を一元管理するクラス。
    orchestra.py がこれをインスタンス化し、各モジュールに状態を伝搬させる。
    """
    def __init__(self, session_id: str = "default_session", persist_dir: str = "./sessions"):
        self.session_id = session_id
        self.persist_dir = persist_dir
        
        # 4つの独立したステート層
        self.routing = RoutingState()
        self.workspace = Workspace()
        self.memory = MemoryLayer()
        self.prefs = UserPreferences()

        # 保存先ディレクトリの確保
        if not os.path.exists(self.persist_dir):
            os.makedirs(self.persist_dir)

    # ---------------------------------------------------------------
    # 状態の更新メソッド群 (orchestra.py や Handler から呼ばれる)
    # ---------------------------------------------------------------
    
    def apply_inspector_result(self, inspector_result: Dict[str, Any]):
        """IntentInspector の解析結果を受け取り、状態を更新する"""
        mode = inspector_result.get("mode", "unknown")
        
        # 意図が不明な場合、過去のモードを維持するかどうかのロジック
        if mode != "unknown":
            self.routing.current_mode = mode
            
        self.routing.active_targets = inspector_result.get("targets", [])
        self.routing.last_intent_score = inspector_result.get("score", 0)
        self.routing.forced_handler = inspector_result.get("forced_handler")

        # UIコンテキストがあればユーザー設定に反映（暗黙の引き継ぎ）
        if inspector_result.get("theme"):
            self.prefs.global_theme = inspector_result.get("theme")
        if inspector_result.get("surface"):
            self.prefs.surface_preference = inspector_result.get("surface")
        if inspector_result.get("responsive"):
            self.prefs.is_responsive_default = True

    def update_workspace(self, code: Optional[str] = None, json_data: Optional[Dict] = None, artifact_name: str = "Untitled"):
        """LLMの生成結果などを受け取り、ワークスペースを更新する"""
        if code:
            self.workspace.current_code = code
        if json_data:
            self.workspace.current_json = json_data
            
        self.workspace.active_artifact_name = artifact_name
        self.workspace.version += 1

    def add_chat_history(self, role: str, content: str):
        """会話履歴を追加する"""
        self.memory.add_message(role, content)

    # ---------------------------------------------------------------
    # プロンプト構築・外部出力用メソッド
    # ---------------------------------------------------------------

    def get_prompt_signals(self) -> Dict[str, Any]:
        """
        PromptBuilder に渡すための「今LLMに教えるべき文脈」を抽出して返す。
        """
        signals = {
            "active_mode": self.routing.current_mode,
            "theme": self.prefs.global_theme,
            "responsive": self.prefs.is_responsive_default,
            "active_context": None,
            "recent_history": [asdict(msg) for msg in self.memory.history[-3:]] # 直近3件のみ
        }
        
        # ワークスペースにコードがあれば「修正」の文脈を付与
        if self.workspace.current_code:
            signals["active_context"] = f"現在 '{self.workspace.active_artifact_name}' (v{self.workspace.version}) を編集しています。"
            signals["base_code"] = self.workspace.current_code

        return signals

    # ---------------------------------------------------------------
    # 永続化（保存・読み込み） - Electron環境で再起動しても状態を維持
    # ---------------------------------------------------------------

    def save_state(self):
        """現在のステートをJSONファイルとして保存する"""
        filepath = os.path.join(self.persist_dir, f"{self.session_id}.json")
        state_dict = {
            "routing": asdict(self.routing),
            "workspace": asdict(self.workspace),
            "memory": asdict(self.memory),
            "prefs": asdict(self.prefs)
        }
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                # 修正: json.dumps ではなく json.dump を使用
                json.dump(state_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f" [ContextManager] 状態の保存に失敗: {e}")

    def load_state(self):
        """保存されたステートをファイルから復元する"""
        filepath = os.path.join(self.persist_dir, f"{self.session_id}.json")
        if not os.path.exists(filepath):
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                state_dict = json.load(f)
                
            # ディクショナリからデータクラスへ復元
            if "routing" in state_dict:
                self.routing = RoutingState(**state_dict["routing"])
            if "workspace" in state_dict:
                self.workspace = Workspace(**state_dict["workspace"])
            if "prefs" in state_dict:
                self.prefs = UserPreferences(**state_dict["prefs"])
                
            # メモリは Message オブジェクトのリストに戻す必要がある
            if "memory" in state_dict:
                mem_data = state_dict["memory"]
                history = [Message(**msg) for msg in mem_data.get("history", [])]
                self.memory = MemoryLayer(
                    history=history,
                    summary=mem_data.get("summary"),
                    max_history_length=mem_data.get("max_history_length", 10)
                )
        except Exception as e:
            print(f" [ContextManager] 状態のロードに失敗: {e}")

# -------------------------------------------------------------------
# 動作確認用
# -------------------------------------------------------------------
if __name__ == "__main__":
    # orchestra.py 内での利用イメージ
    ctx = ContextManager(session_id="dev_session_001")
    
    # 1. ユーザー発話と Inspector の結果を適用
    ctx.add_chat_history("user", "ボタンをダークテーマで作って")
    mock_inspector_result = {
        "mode": "ui_design",
        "targets": ["button"],
        "theme": "dark",
        "score": 85
    }
    ctx.apply_inspector_result(mock_inspector_result)
    
    # 2. LLMが生成したと仮定して Workspace を更新
    ctx.update_workspace(code="<button class='bg-black text-white'>Click</button>", artifact_name="DarkButton")
    ctx.add_chat_history("assistant", "ダークテーマのボタンを作成しました。")
    
    # 3. ユーザーの追加指示（文脈の引き継ぎテスト）
    ctx.add_chat_history("user", "もう少し丸みを持たせて")
    mock_inspector_result_2 = {"mode": "unknown", "targets": [], "score": 20}
    ctx.apply_inspector_result(mock_inspector_result_2) # 意図不明でも、前回の "ui_design" と "dark" は保持される
    
    # PromptBuilder に渡すシグナルの確認
    print(json.dumps(ctx.get_prompt_signals(), ensure_ascii=False, indent=2))
    
    # セーブのテスト（これがないとファイルが生成されません）
    ctx.save_state()