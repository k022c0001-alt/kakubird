import os
import logging
from typing import List, Dict, Any
from supabase import create_client, Client

logger = logging.getLogger(__name__)

class SupabaseManager:
    """
    職業データをSupabase(PostgreSQL)で管理するためのマネージャークラス。
    アプリ用のフィードデータ取得、動画URLの更新、チャット診断用のキーワード検索を提供します。
    """
    def __init__(self, supabase_url: str = None, supabase_key: str = None):
        # 環境変数または引数から接続情報を取得
        self.url = supabase_url or os.environ.get("SUPABASE_URL")
        self.key = supabase_key or os.environ.get("SUPABASE_KEY")
        
        if not self.url or not self.key:
            logger.warning("Supabase URLまたはKeyが未設定です。環境変数をセットしてください。")
            self.supabase = None
        else:
            self.supabase: Client = create_client(self.url, self.key)

    def get_career_feed(self) -> dict:
        """
        [API用] アプリのフィード画面向けに職業リストを取得する
        動画URL(video_url)が存在するものを優先し、カテゴリ順、名前順でソートします。
        """
        if not self.supabase:
            return {"status": "error", "message": "DB未接続", "data": []}

        try:
            # nulls_last=True で動画URLがないものを後ろに回す
            response = self.supabase.table("careers") \
                .select("id, name, category, catchphrase, subjects, skills, video_url") \
                .order("video_url", desc=True, nulls_last=True) \
                .order("category") \
                .order("name") \
                .execute()
            
            data = response.data
            return {
                "status": "success",
                "total_count": len(data),
                "video_count": sum(1 for x in data if x.get("video_url")),
                "data": data
            }
        except Exception as e:
            logger.error(f"フィード取得エラー: {e}")
            return {"status": "error", "message": str(e), "data": []}

    def update_video_url(self, career_id: str, video_url: str) -> dict:
        """
        [管理用] チームメンバーが動画URLを登録・更新するためのメソッド
        """
        if not self.supabase:
            return {"status": "error", "message": "DB未接続"}

        try:
            response = self.supabase.table("careers") \
                .update({"video_url": video_url}) \
                .eq("id", career_id) \
                .execute()
            
            if not response.data:
                return {"status": "error", "message": f"対象のID({career_id})が見つかりませんでした。"}
                
            return {
                "status": "success", 
                "message": "動画URLを更新しました",
                "data": response.data[0]
            }
        except Exception as e:
            logger.error(f"動画URL更新エラー ({career_id}): {e}")
            return {"status": "error", "message": str(e)}

    def search_careers_by_keywords(self, user_keywords: List[str]) -> List[Dict[str, Any]]:
        """
        [分析用] ユーザーの入力から抽出したキーワードをもとに、関連する職業を検索する。
        """
        if not self.supabase or not user_keywords:
            return []
            
        try:
            # 50件程度であれば、全件取得してPython側でスコアリングした方が
            # ゆらぎや同義語対応などの細かい制御がしやすいため高速かつ確実です。
            response = self.supabase.table("careers").select("*").execute()
            all_careers = response.data
            
            matched = []
            for career in all_careers:
                # DB上のJSONB配列をPythonのリストとして処理
                career_kws = career.get("keywords", [])
                
                score = 0
                for ukw in user_keywords:
                    for ckw in career_kws:
                        if ukw in ckw or ckw in ukw:
                            score += 1
                            
                if score > 0:
                    career["match_score"] = score
                    matched.append(career)
                    
            # スコア順にソートして適性の高いものを上にする
            matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)
            return matched

        except Exception as e:
            logger.error(f"適職検索エラー: {e}")
            return []