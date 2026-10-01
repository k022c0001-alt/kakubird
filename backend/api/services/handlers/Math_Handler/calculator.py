# backend/api/services/handlers/MathHandler/calculator.py
"""Safe deterministic evaluator for arithmetic expressions and currency conversion.

LLMによる推論を含まない、純粋かつ安全な数学的処理エンジン。
AST (抽象構文木) を用いて数式をパースし、許可された安全な演算のみを実行します。
"""
from __future__ import annotations

import ast
import logging
import math
import operator
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Mapping, Optional, Tuple, Union

logger = logging.getLogger(__name__)

Number = Union[int, float]

class MathEngineError(ValueError):
    """計算処理中の想定されるエラー。安定したエラーコードを持ちます。"""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }

@dataclass(frozen=True)
class MathEvaluation:
    expression: str
    normalized_expression: str
    result: Number

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

@dataclass(frozen=True)
class _FunctionSpec:
    function: Callable[..., Number]
    min_args: int = 1
    max_args: int = 1

class Calculator:
    """Normalize and evaluate arithmetic after strict AST validation."""

    MAX_INPUT_LENGTH = 1_000
    MAX_EXPRESSION_LENGTH = 300
    MAX_AST_NODES = 100
    MAX_AST_DEPTH = 24
    MAX_LITERAL_DIGITS = 120
    MAX_ABS_LITERAL = 10**100
    MAX_ABS_RESULT = 10**100
    MAX_ABS_EXPONENT = 1_000

    _BINARY_OPERATORS: Mapping[type, Callable[[Number, Number], Number]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _UNARY_OPERATORS: Mapping[type, Callable[[Number], Number]] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    _CONSTANTS: Mapping[str, Number] = {
        "pi": math.pi,
        "e": math.e,
        "tau": math.tau,
    }
    _FUNCTIONS: Mapping[str, _FunctionSpec] = {
        "abs": _FunctionSpec(math.fabs),
        "sqrt": _FunctionSpec(math.sqrt),
        "sin": _FunctionSpec(math.sin),
        "cos": _FunctionSpec(math.cos),
        "tan": _FunctionSpec(math.tan),
        "log": _FunctionSpec(math.log),
        "ln": _FunctionSpec(math.log),
        "log10": _FunctionSpec(math.log10),
        "floor": _FunctionSpec(math.floor),
        "ceil": _FunctionSpec(math.ceil),
        "round": _FunctionSpec(round),
        "degrees": _FunctionSpec(math.degrees),
        "radians": _FunctionSpec(math.radians),
    }

    _PREFIXES = re.compile(
        r"^\s*(?:(?:次|以下)の?\s*)?(?:(?:計算)?式\s*)?(?:を\s*)?"
        r"(?:計算(?:して|してください)?|求めて(?:ください)?|"
        r"calculate|compute|evaluate|solve|答え(?:は|を)?|結果(?:は|を)?)"
        r"\s*[:：]?\s*",
        re.IGNORECASE,
    )
    _SUFFIXES = re.compile(
        r"(?:\s*(?:を\s*)?(?:計算(?:して|してください)?|"
        r"求めて(?:ください)?|教えて(?:ください)?|お願い(?:します)?|"
        r"calculate|compute|evaluate|solve)\s*[?？。！!]*\s*$)"
        r"|(?:\s*(?:の?答え)?(?:は)?(?:いくつ|何)(?:ですか)?\s*[?？。！!]*\s*$)"
        r"|(?:\s*の?(?:答え|結果)(?:は)?\s*[?？。！!]*\s*$)"
        r"|(?:\s*は\s*[?？]\s*$)",
        re.IGNORECASE,
    )

    _NUMBER_OR_GROUP = r"(?:\d+(?:\.\d+)?|\([^()]+\))"
    _BASE_PERCENT = re.compile(
        rf"(?P<base>{_NUMBER_OR_GROUP})\s*の\s*(?P<pct>{_NUMBER_OR_GROUP})\s*%",
        re.IGNORECASE,
    )
    _PERCENT_OF = re.compile(
        rf"(?P<pct>{_NUMBER_OR_GROUP})\s*%\s*(?:of|の)\s*(?P<base>{_NUMBER_OR_GROUP})",
        re.IGNORECASE,
    )
    _PLAIN_PERCENT = re.compile(
        rf"(?P<number>{_NUMBER_OR_GROUP})\s*%",
        re.IGNORECASE,
    )
    _POSTFIX_SQUARE_ROOT = re.compile(
        rf"(?P<value>{_NUMBER_OR_GROUP})\s*の平方根",
    )
    _RADICAL = re.compile(
        rf"√\s*(?P<value>{_NUMBER_OR_GROUP})",
    )
    _THOUSANDS_TOKEN = re.compile(
        r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w.])"
    )
    _VALID_THOUSANDS = re.compile(
        r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$"
    )
    _ALLOWED_CHARACTERS = re.compile(
        r"^[0-9A-Za-z_+\-*/%().\s]*$"
    )
    _INTEGER_LITERAL = re.compile(r"(?<![\w.])\d+(?![\w.])")
    _FLOAT_LITERAL = re.compile(
        r"(?<![\w.])(?:\d+\.\d*|\.\d+)(?:e[+\-]?\d+)?(?![\w.])",
        re.IGNORECASE,
    )

    _SYMBOL_REPLACEMENTS: Mapping[str, str] = {
        "×": "*", "✕": "*", "✖": "*",
        "÷": "/",
        "−": "-", "–": "-", "—": "-",
        "＾": "**", "^": "**",
        "π": "pi", "τ": "tau",
        "=": "", "＝": "",
        "?": "", "？": "",
        "!": "", "！": "",
    }
    _WORD_OPERATOR_REPLACEMENTS: Tuple[Tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"(?:たす|足す|プラス)"), "+"),
        (re.compile(r"(?:ひく|引く|マイナス)"), "-"),
        (re.compile(r"(?:かける|掛ける)"), "*"),
        (re.compile(r"(?:わる|割る)"), "/"),
    )

    # ==========================================
    # API Methods (handler.py から呼ばれるインターフェース)
    # ==========================================

    def evaluate_expression(self, expression: str) -> float:
        """文字列の数式を評価して計算結果の数値を返す（handler.py 互換）"""
        try:
            evaluation = self.evaluate(expression)
            return float(evaluation.result)
        except MathEngineError as e:
            logger.error(f"数式の評価エラー '{expression}': {e.message}")
            raise ValueError(f"計算式のフォーマットが正しくありません: {expression} ({e.message})") from e
        except Exception as e:
            logger.error(f"予期せぬ評価エラー '{expression}': {e}")
            raise ValueError(f"計算中にエラーが発生しました: {expression}") from e

    def convert_currency(self, amount: float, rate: float) -> float:
        """金額と為替レートから換算結果を返す"""
        if rate <= 0:
            raise ValueError("無効な為替レートです。")
        return round(float(amount) * float(rate), 2)

    # ==========================================
    # Core Engine Methods (高度な構文解析・正規化)
    # ==========================================

    def evaluate(self, expression: str) -> MathEvaluation:
        """文字列を正規化・AST解析し、安全に計算結果を算出する"""
        if not isinstance(expression, str):
            raise MathEngineError("invalid_expression", "計算式は文字列で指定してください。")

        original = expression.strip()
        if not original:
            raise MathEngineError("empty_expression", "計算式が空です。")
        if len(original) > self.MAX_INPUT_LENGTH:
            raise MathEngineError("expression_too_long", f"入力は{self.MAX_INPUT_LENGTH}文字以内にしてください。")

        normalized = self.normalize(original)
        if not normalized:
            raise MathEngineError("empty_expression", "計算式が空です。")
        if len(normalized) > self.MAX_EXPRESSION_LENGTH:
            raise MathEngineError("expression_too_long", f"計算式は{self.MAX_EXPRESSION_LENGTH}文字以内にしてください。")

        self._validate_literal_lengths(normalized)
        try:
            tree = ast.parse(normalized, mode="eval")
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise MathEngineError("invalid_expression", "計算式の形式を確認してください。") from exc

        if sum(1 for _ in ast.walk(tree)) > self.MAX_AST_NODES:
            raise MathEngineError("expression_too_complex", "計算式が複雑すぎます。")
        if self._ast_depth(tree) > self.MAX_AST_DEPTH:
            raise MathEngineError("expression_too_deep", "括弧または演算の入れ子が深すぎます。")

        result = self._evaluate_node(tree.body)
        result = self._validate_number(result, code="numeric_overflow")
        
        # 整数の場合はint型にキャストして綺麗にする
        if isinstance(result, float) and result.is_integer():
            result = int(result)

        return MathEvaluation(
            expression=original,
            normalized_expression=normalized,
            result=result,
        )

    def normalize(self, expression: str) -> str:
        """未知の文字列を削除せず、計算可能な形式に正規化する"""
        text = unicodedata.normalize("NFKC", expression).strip()
        text = self._strip_known_phrases(text)

        for source, target in self._SYMBOL_REPLACEMENTS.items():
            text = text.replace(source, target)
        for pattern, replacement in self._WORD_OPERATOR_REPLACEMENTS:
            text = pattern.sub(replacement, text)

        text = re.sub(r"パーセント", "%", text)
        text = self._normalize_thousands_separators(text)
        text = self._normalize_square_roots(text)
        text = self._normalize_percentages(text)
        text = self._strip_known_phrases(text)

        if not self._ALLOWED_CHARACTERS.fullmatch(text):
            invalid = self._first_invalid_character(text)
            display = repr(invalid) if invalid else "不明"
            raise MathEngineError("unsupported_character", f"計算式に使用できない文字が含まれています: {display}")

        # 空白は文法的な意味を持たないため削除
        text = re.sub(r"\s+", "", text)
        if not text:
            raise MathEngineError("empty_expression", "計算式が空です。")
        return text

    # ==========================================
    # Internal Helpers
    # ==========================================

    def _normalize_percentages(self, text: str) -> str:
        previous: Optional[str] = None
        current = text
        for _ in range(8):
            if current == previous:
                break
            previous = current
            current = self._BASE_PERCENT.sub(
                lambda match: f"({match.group('base')})*({match.group('pct')}/100)", current
            )
            current = self._PERCENT_OF.sub(
                lambda match: f"({match.group('pct')}/100)*({match.group('base')})", current
            )
            current = self._PLAIN_PERCENT.sub(
                lambda match: f"({match.group('number')}/100)", current
            )
        return current

    def _normalize_square_roots(self, text: str) -> str:
        text = self._POSTFIX_SQUARE_ROOT.sub(lambda match: f"sqrt({match.group('value')})", text)
        return self._RADICAL.sub(lambda match: f"sqrt({match.group('value')})", text)

    def _normalize_thousands_separators(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            token = match.group(0)
            if "," not in token:
                return token
            if not self._VALID_THOUSANDS.fullmatch(token):
                raise MathEngineError("invalid_number_format", f"桁区切りの形式を確認してください: {token}")
            return token.replace(",", "")

        normalized = self._THOUSANDS_TOKEN.sub(replace, text)
        if "," in normalized:
            raise MathEngineError("invalid_number_format", "カンマは3桁ごとの数値区切りにだけ使用できます。")
        return normalized

    def _strip_known_phrases(self, text: str) -> str:
        current = text.strip()
        for _ in range(4):
            changed = self._PREFIXES.sub("", current).strip()
            changed = self._SUFFIXES.sub("", changed).strip()
            if changed == current:
                return current
            current = changed
        return current

    def _evaluate_node(self, node: ast.AST) -> Number:
        # Python 3.8以降の定数対応
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise MathEngineError("unsupported_value", "数値以外は計算できません。")
            return self._validate_number(node.value, code="number_too_large", literal=True)
            
        # 古いPython (3.7以前) の対応
        elif hasattr(ast, 'Num') and isinstance(node, getattr(ast, 'Num')):
            return self._validate_number(getattr(node, "n"), code="number_too_large", literal=True)

        if isinstance(node, ast.Name):
            value = self._CONSTANTS.get(node.id.casefold())
            if value is None:
                raise MathEngineError("unknown_identifier", f"使用できない名前です: {node.id}")
            return value

        if isinstance(node, ast.UnaryOp):
            operation = self._UNARY_OPERATORS.get(type(node.op))
            if operation is None:
                raise MathEngineError("unsupported_operation", "対応していない単項演算です。")
            operand = self._evaluate_node(node.operand)
            return self._validate_number(operation(operand), code="numeric_overflow")

        if isinstance(node, ast.BinOp):
            operation = self._BINARY_OPERATORS.get(type(node.op))
            if operation is None:
                raise MathEngineError("unsupported_operation", "対応していない演算です。")
            left = self._evaluate_node(node.left)
            right = self._evaluate_node(node.right)
            if isinstance(node.op, ast.Pow):
                self._validate_power(left, right)
            try:
                result = operation(left, right)
            except ZeroDivisionError as exc:
                raise MathEngineError("division_by_zero", "0では割れません。") from exc
            except (OverflowError, ValueError) as exc:
                raise MathEngineError("numeric_overflow", "計算結果が大きすぎるか、実数の範囲外です。") from exc
            return self._validate_number(result, code="numeric_overflow")

        if isinstance(node, ast.Call):
            return self._evaluate_call(node)

        raise MathEngineError("unsupported_expression", "使用できるのは数値、定数、基本関数、括弧、+、-、*、/、//、%、**だけです。")

    def _evaluate_call(self, node: ast.Call) -> Number:
        if not isinstance(node.func, ast.Name):
            raise MathEngineError("unsupported_function", "属性アクセスやメソッド呼び出しは使用できません。")
        if node.keywords:
            raise MathEngineError("unsupported_function_arguments", "関数のキーワード引数は使用できません。")

        name = node.func.id.casefold()
        spec = self._FUNCTIONS.get(name)
        if spec is None:
            raise MathEngineError("unsupported_function", f"使用できない関数です: {node.func.id}")
        if not spec.min_args <= len(node.args) <= spec.max_args:
            raise MathEngineError("invalid_function_arguments", f"{name}()の引数は{spec.min_args}〜{spec.max_args}個必要です。")

        arguments = [self._evaluate_node(argument) for argument in node.args]
        try:
            result = spec.function(*arguments)
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise MathEngineError("math_domain_error", f"{name}()の入力値が計算可能な範囲外です。") from exc
        return self._validate_number(result, code="numeric_overflow")

    def _validate_power(self, base: Number, exponent: Number) -> None:
        if abs(exponent) > self.MAX_ABS_EXPONENT:
            raise MathEngineError("exponent_too_large", "指数が大きすぎます。")
        if base == 0 and exponent < 0:
            raise MathEngineError("division_by_zero", "0では割れません。")
        if base == 0:
            return

        absolute_base = abs(base)
        if absolute_base == 1:
            return
        try:
            estimated_log10 = exponent * math.log10(absolute_base)
        except (ValueError, OverflowError):
            return
        if estimated_log10 > math.log10(self.MAX_ABS_RESULT) + 1:
            raise MathEngineError("numeric_overflow", "計算結果が大きすぎます。")

    def _validate_number(self, value: object, *, code: str, literal: bool = False) -> Number:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MathEngineError("unsupported_value", "実数として扱えない結果です。")
        if isinstance(value, float) and not math.isfinite(value):
            raise MathEngineError(code, "計算結果が有限値ではありません。")
        
        limit = self.MAX_ABS_LITERAL if literal else self.MAX_ABS_RESULT
        if abs(value) > limit:
            message = "数値が大きすぎます。" if literal else "計算結果が大きすぎます。"
            raise MathEngineError(code, message)
        return value

    def _validate_literal_lengths(self, expression: str) -> None:
        without_floats = self._FLOAT_LITERAL.sub("0", expression)
        for match in self._INTEGER_LITERAL.finditer(without_floats):
            if len(match.group(0).lstrip("0")) > self.MAX_LITERAL_DIGITS:
                raise MathEngineError("number_too_large", "数値の桁数が大きすぎます。")

    @classmethod
    def _first_invalid_character(cls, text: str) -> str:
        for character in text:
            if not re.fullmatch(r"[0-9A-Za-z_+\-*/%().\s]", character):
                return character
        return ""

    @classmethod
    def _ast_depth(cls, node: ast.AST) -> int:
        children = list(ast.iter_child_nodes(node))
        if not children:
            return 1
        return 1 + max(cls._ast_depth(child) for child in children)

__all__ = ["MathEngineError", "MathEvaluation", "Calculator"]