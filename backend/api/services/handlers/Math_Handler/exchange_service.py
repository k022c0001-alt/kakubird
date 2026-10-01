# backend/api/services/handlers/MathHandler/exchange_service.py
import logging
from typing import Optional

# 外部API用のサーチャークラスがある想定
# from CurrencySearcher import CurrencySearcher 

logger = logging.getLogger(__name__)

class ExchangeService:
    def __init__(self):
        # self.searcher = CurrencySearcher()
        self._cache = {}

    async def get_rate(self, base: str, target: str) -> float:
        """指定された通貨ペアのレートを取得する"""
        cache_key = f"{base}_{target}"
        
        # キャッシュがあればそれを使うなどの安全対策
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            logger.debug(f"外部APIからレートを取得中: {base} -> {target}")
            # 実際は外部APIやCurrencySearcherを呼び出す
            # rate = await self.searcher.fetch(base, target)
            
            # ダミーデータ（例: 1 JPY = 0.025 PLN (1PLN = 40円)）
            rate = 0.025 
            
            self._cache[cache_key] = rate
            return rate
            
        except Exception as e:
            logger.error(f"為替レート取得失敗 ({base} -> {target}): {e}")
            raise RuntimeError("為替レートの取得に失敗しました。時間をおいて再試行してください。") from e