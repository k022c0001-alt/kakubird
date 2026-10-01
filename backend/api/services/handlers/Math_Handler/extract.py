# backend/api/services/handlers/MathHandler/extract.py
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

# ========================================================
# 1. 汎用ユーティリティ関数
# ========================================================

def message_text(message: Any) -> str:
    return message.strip() if isinstance(message, str) else str(message or "").strip()

def extract_message(request: Any) -> str:
    if isinstance(request, str):
        return request.strip()
    if isinstance(request, Mapping):
        for key in ("message", "prompt", "query", "text", "content"):
            value = request.get(key)
            if value is not None and str(value).strip():
                return message_text(value)
        return ""
    for attribute in ("message", "prompt", "query", "text", "content"):
        value = getattr(request, attribute, None)
        if value is not None and str(value).strip():
            return message_text(value)
    return ""

def extract_signals(request: Any) -> Dict[str, Any]:
    if isinstance(request, Mapping):
        value = request.get("current_signals") or request.get("signals") or {}
    else:
        value = getattr(request, "current_signals", None) or getattr(request, "signals", None) or {}
    return dict(value) if isinstance(value, Mapping) else {}

def normalized_signal(value: Any) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


# ========================================================
# 2. 自然言語からの数式・為替抽出ロジック
# ========================================================

@dataclass
class ExtractedMath:
    formula: str = ""
    is_currency_conversion: bool = False
    base_currency: str = ""
    target_currency: str = ""
    amount: float = 0.0

class Extractor:
    def extract(self, text: str) -> ExtractedMath:
        """
        自然言語のテキストから、数式または為替変換の意図を抽出します。
        インジェクション対策としてホワイトリスト検証を行い、安全な式のみを返します。
        """
        
        # 1. 通貨変換のパターンに合致するかチェック
        currency_pattern = r'([\d,]+(?:\.\d+)?)\s*(円|ドル|ユーロ|ウォン|ズウォティ|USD|JPY|EUR|KRW|PLN).*(円|ドル|ユーロ|ウォン|ズウォティ|USD|JPY|EUR|KRW|PLN)'
        currency_match = re.search(currency_pattern, text, re.IGNORECASE)
        
        if currency_match:
            amount_str = currency_match.group(1).replace(',', '')
            try:
                amount = float(amount_str)
                return ExtractedMath(
                    is_currency_conversion=True,
                    amount=amount,
                    base_currency=currency_match.group(2),
                    target_currency=currency_match.group(3)
                )
            except ValueError:
                pass 
        
        # 2. 自然言語からの数式抽出（単位変換とインジェクション対策付き）
        # アルファベットの単位(eやinf)を扱うため小文字に統一
        text_lower = text.lower()
        
        # 2-1. 無限大の置換
        text_lower = re.sub(r'無限大数|無限|∞', 'inf', text_lower)
        
        # 2-2. 日本語単位の置換 (数字や閉じ括弧の直後にある場合のみ置換)
        # 例: "220億" -> "220*1e8"
        unit_map = {
            "ミリ": "*1e-3",
            "センチ": "*1e-2",
            "キロ": "*1e3",
            "万": "*1e4",
            "億": "*1e8",
            "兆": "*1e12",
            "ペタ": "*1e15",
            "無量大数": "*1e68",
        }
        for jp_unit, math_val in unit_map.items():
            text_lower = re.sub(rf'(?<=[\d\.\)])\s*{jp_unit}', math_val, text_lower)
            
        # 2-3. ホワイトリストによるサニタイズ (強力なインジェクション対策)
        # 数学に関係のない日本語や、悪意のあるアルファベット(os, import等)をここで全て消去します。
        # 許可: 数字, +, -, *, /, %, ^, (, ), ., e (指数), i, n, f (inf), スペース
        allowed_chars = set("0123456789+-*/%^().einf ")
        sanitized = "".join(c for c in text_lower if c in allowed_chars).strip()
        
        # 2-4. 厳密な数式パターンの抽出 (ゴミ文字の排除)
        # サニタイズ結果から、「数字・inf・括弧」で始まり、演算子を含む最も長い数式の塊を探します。
        # 例: "f12" -> 演算子がないためマッチせず安全に破棄される。
        expression_pattern = re.compile(
            r'(?:inf|\d|\()\s*'               # 始まり (inf, 数字, 開き括弧)
            r'[0-9\+\-\*\/\%\^\(\)\.\seinf]*' # 中間の許可文字
            r'[\+\-\*\/\%\^]'                 # 必須となる演算子 (最低1つ)
            r'[0-9\+\-\*\/\%\^\(\)\.\seinf]*' # 中間の許可文字
            r'(?:inf|\d|\))'                  # 終わり (inf, 数字, 閉じ括弧)
        )
        
        match = expression_pattern.search(sanitized)
        clean_formula = ""
        
        if match:
            clean_formula = match.group(0).strip()
        else:
            # 演算子が含まれない場合でも、明確な「計算依頼」があれば単一の数値を許容する
            math_keywords = ["計算", "たす", "足す", "プラス", "ひく", "引く", "マイナス", 
                             "かける", "掛ける", "わる", "割る", "答え", "合計", "平均", "換算"]
            if any(keyword in text for keyword in math_keywords):
                num_match = re.search(r'(?:inf|\d+(?:\.\d+)?(?:e[+-]?\d+)?)', sanitized)
                if num_match:
                    clean_formula = num_match.group(0)
                    
        # 2-5. DoS攻撃対策: 指数爆発の制限 (計算リソースの枯渇防止)
        # 9999**9999 などの巨大な累乗計算をブロックします。
        if "**" in clean_formula or "^" in clean_formula:
            if re.search(r'(?:\*\*|\^)\s*[0-9]{4,}', clean_formula):
                logger.warning(f"巨大な累乗計算を検知したためブロックしました: {clean_formula}")
                clean_formula = ""
                
        return ExtractedMath(formula=clean_formula)


# ========================================================
# 3. LLM出力・コードブロックからの抽出ロジック
# ========================================================

class MathExtractor:
    """テキストから数式やPythonコードブロックを抽出するクラス。"""

    _CODE_BLOCK_PATTERN = re.compile(
        r"```(?:python|py)?\s*(.*?)```",
        re.IGNORECASE | re.DOTALL
    )

    _INLINE_MATH_PATTERN = re.compile(
        r"^\s*([\d\.\+\-\*\/\%\(\)\s]+)\s*$"
    )

    @classmethod
    def extract_python_code(cls, text: str) -> Optional[str]:
        if not text:
            return None

        matches = cls._CODE_BLOCK_PATTERN.findall(text)
        if matches:
            extracted = matches[0].strip()
            if extracted:
                return extracted

        heuristics_match = (
            "def " in text or
            "print(" in text or
            "import " in text
        )

        has_japanese_explanation = "です" in text or "ます" in text or "以下に" in text

        if heuristics_match and not has_japanese_explanation:
            logger.debug("MarkdownタグなしのPythonコードを検出しました。フォールバックを適用します。")
            return text.strip()

        logger.debug("有効なPythonコードブロックが見つかりませんでした。")
        return None

    @classmethod
    def extract_simple_math(cls, text: str) -> Optional[str]:
        if not text:
            return None

        clean_text = text.replace(" ", "").replace(" ", "")
        match = cls._INLINE_MATH_PATTERN.match(clean_text)
        if match:
            return match.group(1)

        return None

# ========================================================
# 公開API定義
# ========================================================
__all__ = [
    "message_text",
    "extract_message",
    "extract_signals",
    "normalized_signal",
    "ExtractedMath",
    "Extractor",
    "MathExtractor",
]