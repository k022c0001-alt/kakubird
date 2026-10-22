続けよう。前回のComfyUI連携を土台に、今回は**画像生成 → 既存イラストを使った修正 → 顔や手などの部分修正 → 修正結果の検証**まで、既存の `image_animation_ai` の設計につながるように進める。

この開発で重要なのは、単に画像を生成できるようにすることではない。目標は、**自分で描いたキャラクターの特徴を維持しながら、必要な箇所だけAIに修正させること**だ。

そのため、今回は次の順序で実装を整える。

1. ComfyUIプロバイダーのエラー処理と生成処理を改善する。
2. `txt2img`・`img2img`・`inpaint` のワークフローを区別する。
3. 既存の `RepairPlanner` と `ImageRepairService` を接続できる形にする。
4. ComfyUIが起動していなくてもテストできるようにする。
5. 実際の環境で動かす際の確認項目を明確にする。

なお、ここで示すコードは既存ファイルとの接続を想定した実装案だ。実際のプロジェクトに書き込んだり、ComfyUIを起動して動作確認したりしたわけではないので、既存クラスの定義との整合性はテストで確認する。

## 1. まず、画像生成と部分修正の役割を分離する

それぞれの用途を明確にしておく。

| 処理            | 用途             | 例                    |
| ------------- | -------------- | -------------------- |
| `txt2img`     | 新しい画像を生成       | キャラクターの立ち絵を作る        |
| `img2img`     | 元画像を参考に画像を再生成  | 自分の絵を参考に別のポーズを作る     |
| `inpaint`     | マスクした領域を重点的に修正 | 手だけ、目だけ、服の一部だけを直す    |
| `consistency` | 元画像と生成画像を比較    | 髪型、顔、配色、画風が維持されたか調べる |
| `repair_loop` | 修正と検証を繰り返す     | 手を直し、改善したか再評価する      |

ここで注意したいのは、`img2img` や `inpaint` を使えば必ずキャラクターの同一性が保たれるわけではない点だ。モデル、LoRA、元画像、プロンプト、ノイズ除去の強さなどを組み合わせて制御する必要がある。

## 2. ComfyUIプロバイダーを改善する

まず `integrations/comfyui/comfyui_image_provider.py` を改善する。

今回のポイントは、**ワークフローが見つからない場合や生成に失敗した場合も、アプリ全体が突然停止しないようにすること**と、3種類の画像処理を共通の入口から呼び出せるようにすることだ。

### `integrations/comfyui/comfyui_image_provider.py`

```python
# -*- coding: utf-8 -*-
"""
ComfyUIImageProvider.py

ComfyUIを使ったローカル画像生成プロバイダー。

対応する処理:
- txt2img: テキストから画像を生成
- img2img: 既存画像を参考に画像を生成
- inpaint: マスク領域を修正

注意:
ワークフローJSONのノードIDと入力名は、
使用するComfyUIワークフローに合わせて設定すること。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ai.image.generation_request import GenerationRequest
from ai.image.generation_result import GenerationResult
from ai.image.image_generation_provider import ImageGenerationProvider

from integrations.comfyui.comfyui_client import ComfyUIClient
from integrations.comfyui.workflow_builder import WorkflowBuilder


class ComfyUIImageProvider(ImageGenerationProvider):
    """ComfyUIを既存の画像生成インターフェースに接続する。"""

    def __init__(
        self,
        client: ComfyUIClient,
        workflow_builder: WorkflowBuilder,
        output_dir: str | Path = "storage/generated",
        default_workflow: str = "txt2img",
    ) -> None:
        self.client = client
        self.workflow_builder = workflow_builder
        self.output_dir = Path(output_dir)
        self.default_workflow = default_workflow

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def health_check(self) -> bool:
        """ComfyUIに接続できるかを確認する。"""
        try:
            result = self.client.health_check()

            # クライアントの実装差を吸収する。
            if isinstance(result, bool):
                return result

            if isinstance(result, dict):
                return bool(result.get("success", False))

            return bool(result)

        except Exception:
            return False

    def generate(
        self,
        request: GenerationRequest,
    ) -> GenerationResult:
        """テキストから画像を生成する。"""
        return self._run_workflow(
            workflow_name="txt2img",
            request=request,
        )

    def image_to_image(
        self,
        source_image: str | Path,
        request: GenerationRequest,
    ) -> GenerationResult:
        """既存画像を参考に画像を生成する。"""
        source = Path(source_image)

        if not source.is_file():
            return self._failure(
                message="img2imgの元画像が見つかりません。",
                errors=[f"source_image_not_found: {source}"],
            )

        return self._run_workflow(
            workflow_name="img2img",
            request=request,
            source_image=source,
        )

    def inpaint(
        self,
        source_image: str | Path,
        mask_image: str | Path,
        request: GenerationRequest,
    ) -> GenerationResult:
        """マスク領域を中心に画像を修正する。"""
        source = Path(source_image)
        mask = Path(mask_image)

        missing = []

        if not source.is_file():
            missing.append(f"source_image_not_found: {source}")

        if not mask.is_file():
            missing.append(f"mask_image_not_found: {mask}")

        if missing:
            return self._failure(
                message="inpaintに必要なファイルがありません。",
                errors=missing,
            )

        return self._run_workflow(
            workflow_name="inpaint",
            request=request,
            source_image=source,
            mask_image=mask,
        )

    def _run_workflow(
        self,
        workflow_name: str,
        request: GenerationRequest,
        source_image: Optional[Path] = None,
        mask_image: Optional[Path] = None,
    ) -> GenerationResult:
        """ワークフローの構築から画像保存までを実行する。"""

        try:
            config = request.config

            values: dict[str, Any] = {
                "prompt": (
                    request.prompt
                    or getattr(config, "prompt", "")
                    or ""
                ),
                "negative_prompt": (
                    request.negative_prompt
                    or getattr(config, "negative_prompt", "")
                    or ""
                ),
                "width": getattr(config, "width", 1024),
                "height": getattr(config, "height", 1024),
                "steps": getattr(config, "steps", 25),
                "cfg": getattr(config, "guidance_scale", 7.0),
                "seed": getattr(config, "seed", -1),
                "denoise": getattr(config, "denoise_strength", 0.65),
                "checkpoint": getattr(config, "model_name", ""),
                "lora_name": getattr(config, "lora_name", ""),
                "lora_strength": getattr(config, "lora_strength", 1.0),
            }

            # 既存の条件をワークフローに渡す。
            # ワークフロー側に対応するマッピングがある場合のみ反映される。
            conditions = getattr(request, "conditions", None)

            if isinstance(conditions, dict):
                values["conditions"] = conditions

            metadata = getattr(request, "metadata", None)

            if isinstance(metadata, dict):
                values["metadata"] = metadata

            # 元画像・マスクをComfyUIへアップロードする。
            if source_image is not None:
                uploaded_source = self.client.upload_image(
                    source_image
                )
                values["source_image"] = self._uploaded_name(
                    uploaded_source
                )

            if mask_image is not None:
                uploaded_mask = self.client.upload_image(
                    mask_image
                )
                values["mask_image"] = self._uploaded_name(
                    uploaded_mask
                )

            # WorkflowBuilderが論理名からノード入力へ変換する。
            workflow = self.workflow_builder.build(
                workflow_name=workflow_name,
                values=values,
            )

            validation_errors = (
                self.workflow_builder.validate_workflow(workflow)
            )

            if validation_errors:
                return self._failure(
                    message="ワークフローの検証に失敗しました。",
                    errors=[str(error) for error in validation_errors],
                    metadata={"workflow_name": workflow_name},
                )

            result = self.client.generate(workflow)

            if not isinstance(result, dict):
                return self._failure(
                    message="ComfyUIから不正な形式の結果が返されました。",
                    errors=["invalid_comfyui_result"],
                )

            if not result.get("success"):
                return self._failure(
                    message=str(
                        result.get("message", "画像生成に失敗しました。")
                    ),
                    errors=[
                        str(error)
                        for error in result.get("errors", [])
                    ],
                    metadata={
                        "workflow_name": workflow_name,
                        "comfyui_result": result,
                    },
                )

            images = result.get("images", [])

            if not images:
                return self._failure(
                    message="生成処理は終了しましたが、画像がありません。",
                    errors=["generated_image_missing"],
                    metadata={
                        "workflow_name": workflow_name,
                        "prompt_id": result.get("prompt_id"),
                    },
                )

            # 現時点では最初の出力画像を採用する。
            first_image = images[0]

            image_path = (
                first_image.get("path")
                if isinstance(first_image, dict)
                else first_image
            )

            if not image_path:
                return self._failure(
                    message="生成画像の保存先を取得できませんでした。",
                    errors=["generated_image_path_missing"],
                )

            image_path = Path(image_path)

            if not image_path.is_file():
                return self._failure(
                    message="生成画像のファイルが見つかりません。",
                    errors=[f"generated_file_not_found: {image_path}"],
                )

            return GenerationResult(
                success=True,
                image_path=str(image_path),
                seed=values["seed"],
                model_name=values["checkpoint"],
                message="画像生成に成功しました。",
                errors=[],
                metadata={
                    "workflow_name": workflow_name,
                    "prompt_id": result.get("prompt_id"),
                    "source_image": (
                        str(source_image)
                        if source_image is not None
                        else None
                    ),
                    "mask_image": (
                        str(mask_image)
                        if mask_image is not None
                        else None
                    ),
                    "comfyui_metadata": result.get("metadata", {}),
                },
            )

        except Exception as exc:
            # ワークフロー未登録、接続失敗、HTTPエラーなどを
            # GenerationResultに変換する。
            return self._failure(
                message=f"{workflow_name}の実行に失敗しました。",
                errors=[
                    f"{type(exc).__name__}: {exc}"
                ],
                metadata={"workflow_name": workflow_name},
            )

    @staticmethod
    def _uploaded_name(upload_result: Any) -> str:
        """アップロード結果からLoadImage等に渡す名前を取り出す。"""

        if isinstance(upload_result, str):
            return upload_result

        if isinstance(upload_result, dict):
            name = upload_result.get("name")

            if name:
                subfolder = upload_result.get("subfolder", "")

                if subfolder:
                    return f"{subfolder}/{name}"

                return str(name)

        raise ValueError(
            "ComfyUIのアップロード結果から画像名を取得できません。"
        )

    @staticmethod
    def _failure(
        message: str,
        errors: list[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> GenerationResult:
        return GenerationResult(
            success=False,
            image_path=None,
            seed=None,
            model_name=None,
            message=message,
            errors=errors,
            metadata=metadata or {},
        )
```

### このコードで改善した点

* 元画像やマスクが存在しない場合に、生成処理を開始しない。
* `txt2img`・`img2img`・`inpaint` を別のワークフローとして呼び出す。
* ComfyUIの接続失敗やワークフローエラーを `GenerationResult` にまとめる。
* 生成結果のファイルが本当に存在するか確認する。
* 元画像やマスクなどの情報を、後から検証できるようにメタデータに残す。

**既存コードとの互換性について:** この実装は `GenerationResult` が `image_path=None` などを受け入れること、`WorkflowBuilder.validate_workflow()` がエラー一覧を返すことを想定している。実際の定義が異なる場合は、既存クラスの仕様に合わせて調整する必要がある。

## 3. 3種類のワークフローを登録する

次に、`integrations/comfyui/__init__.py` を整理する。

ここで重要なのは、**ワークフローの登録と、ワークフローの中身を別々に管理すること**だ。あとからSDXLや別の画像生成モデルに切り替えても、アプリ本体を大きく変更せずに済む。

例えば、次の構成にする。

```text
integrations/
└── comfyui/
    ├── __init__.py
    ├── comfyui_client.py
    ├── comfyui_image_provider.py
    ├── workflow_builder.py
    ├── workflow_registry.py
    └── workflows/
        ├── txt2img.json
        ├── img2img.json
        └── inpaint.json
```

### ワークフローごとの入力マッピング

`WorkflowBuilder` が受け取る論理名と、ComfyUI側のノード入力を対応させる。

| 論理名               | `txt2img`  | `img2img`  | `inpaint`  |
| ----------------- | ---------- | ---------- | ---------- |
| `checkpoint`      | モデル読込ノード   | モデル読込ノード   | モデル読込ノード   |
| `prompt`          | ポジティブプロンプト | ポジティブプロンプト | ポジティブプロンプト |
| `negative_prompt` | ネガティブプロンプト | ネガティブプロンプト | ネガティブプロンプト |
| `seed`            | サンプラー      | サンプラー      | サンプラー      |
| `steps`           | サンプラー      | サンプラー      | サンプラー      |
| `cfg`             | サンプラー      | サンプラー      | サンプラー      |
| `width`, `height` | 空の潜在画像     | 元画像から取得・調整 | 元画像から取得・調整 |
| `source_image`    | 不要         | 元画像の読込ノード  | 元画像の読込ノード  |
| `mask_image`      | 不要         | 不要         | マスクの読込ノード  |
| `denoise`         | 通常は不要      | サンプラー      | サンプラー      |

この表をそのままノードIDとして扱うのではなく、各JSONファイル側に実際のノードIDを設定する。

特に `inpaint` では、マスク画像を読み込むだけでは修正処理は完成しない。マスクの出力を、`VAEEncodeForInpaint` などの対応ノードにつなぐ必要がある。

また、ComfyUIにアップロードした画像の名前やサブフォルダーの扱いは、実際のアップロード結果とワークフローの仕様を照合する必要がある。

### `integrations/comfyui/__init__.py`

既存の生成処理から、プロバイダーを簡単に生成できる入口を用意する。

```python
# -*- coding: utf-8 -*-
"""ComfyUI連携の生成入口。"""

from pathlib import Path

from integrations.comfyui.comfyui_client import ComfyUIClient
from integrations.comfyui.comfyui_image_provider import (
    ComfyUIImageProvider,
)
from integrations.comfyui.workflow_builder import WorkflowBuilder
from integrations.comfyui.workflow_registry import WorkflowRegistry


def create_comfyui_provider(
    base_url: str = "http://127.0.0.1:8188",
    workflow_dir: str | Path = (
        "integrations/comfyui/workflows"
    ),
    output_dir: str | Path = "storage/generated",
) -> ComfyUIImageProvider:
    """
    ComfyUIプロバイダーを生成する。

    workflow_dirには、実際に利用するAPI形式の
    ワークフローJSONを配置する。
    """

    registry = WorkflowRegistry()

    workflow_dir = Path(workflow_dir)

    # ファイルが存在するワークフローだけを登録する。
    # まだ作成していないimg2imgやinpaintを誤って
    # 利用可能と判定しないための仕組み。
    workflow_files = {
        "txt2img": workflow_dir / "txt2img.json",
        "img2img": workflow_dir / "img2img.json",
        "inpaint": workflow_dir / "inpaint.json",
    }

    node_maps = {
        "txt2img": {
            "checkpoint": {
                "node": "4",
                "input": "ckpt_name",
            },
            "prompt": {
                "node": "6",
                "input": "text",
            },
            "negative_prompt": {
                "node": "7",
                "input": "text",
            },
            "seed": {
                "node": "3",
                "input": "seed",
            },
            "steps": {
                "node": "3",
                "input": "steps",
            },
            "cfg": {
                "node": "3",
                "input": "cfg",
            },
            "width": {
                "node": "5",
                "input": "width",
            },
            "height": {
                "node": "5",
                "input": "height",
            },
        },

        # 以下のノードIDは例。
        # img2img.jsonの実際のノードIDに合わせること。
        "img2img": {
            "checkpoint": {
                "node": "4",
                "input": "ckpt_name",
            },
            "prompt": {
                "node": "6",
                "input": "text",
            },
            "negative_prompt": {
                "node": "7",
                "input": "text",
            },
            "seed": {
                "node": "3",
                "input": "seed",
            },
            "steps": {
                "node": "3",
                "input": "steps",
            },
            "cfg": {
                "node": "3",
                "input": "cfg",
            },
            "denoise": {
                "node": "3",
                "input": "denoise",
            },
            "source_image": {
                "node": "10",
                "input": "image",
            },
        },

        # 以下のノードIDは例。
        # inpaint.jsonの実際のノードIDに合わせること。
        "inpaint": {
            "checkpoint": {
                "node": "4",
                "input": "ckpt_name",
            },
            "prompt": {
                "node": "6",
                "input": "text",
            },
            "negative_prompt": {
                "node": "7",
                "input": "text",
            },
            "seed": {
                "node": "3",
                "input": "seed",
            },
            "steps": {
                "node": "3",
                "input": "steps",
            },
            "cfg": {
                "node": "3",
                "input": "cfg",
            },
            "denoise": {
                "node": "3",
                "input": "denoise",
            },
            "source_image": {
                "node": "10",
                "input": "image",
            },
            "mask_image": {
                "node": "12",
                "input": "image",
            },
        },
    }

    for name, path in workflow_files.items():
        if not path.is_file():
            continue

        registry.register(
            name=name,
            definition={
                "workflow_path": str(path),
                "node_map": node_maps[name],
            },
        )

    builder = WorkflowBuilder(registry)

    client = ComfyUIClient(
        base_url=base_url,
        output_dir=output_dir,
    )

    return ComfyUIImageProvider(
        client=client,
        workflow_builder=builder,
        output_dir=output_dir,
    )


__all__ = [
    "ComfyUIImageProvider",
    "create_comfyui_provider",
]
```

**この登録コードは、既存の `WorkflowRegistry` と `WorkflowBuilder` が上記の `definition` 形式を受け取ることを前提にしている。** 前回の実装とキーの構造が異なる場合は、そちらに合わせる必要がある。また、マッピングを登録しただけでは画像処理は完成しない。各ワークフローのノード接続も正しく設定しなければならない。

実装時は、ComfyUIの画面で作成したワークフローをAPI形式で出力し、そのJSONのノードID・入力名を確認してから登録するのが安全だ。

## 4. `ImageRepairService` を部分修正と画像全体の修正に対応させる

ここが、今回の開発で特に重要な部分だ。

前回の設計では、`RepairPlanner` が修正計画を立てられる一方で、`ImageRepairService` は `inpaint` を中心にしていた。このままだと、画風やポーズなど、画像全体を調整したいケースに対応しにくい。

そこで、修正対象に応じて処理を切り替える。

* **顔・手・細部**：マスクを使った `inpaint`
* **ポーズ・画風・キャラクター全体**：元画像を参考にする `img2img`
* **マスクが作れない場合**：部分修正を勝手に画像全体の修正に切り替えず、エラーとして返す

最後のルールは大切だ。顔だけ直したいのに画像全体を再生成して、キャラクターが別人になってしまうのを防ぐためだ。

### `ai/consistency/image_repair_service.py`

既存の `ImageRepairService` を置き換える場合の実装例だ。既存のコンストラクターや呼び出し元との互換性は、プロジェクト側の定義に合わせて調整してほしい。

```python
# -*- coding: utf-8 -*-
"""
ImageRepairService.py

修正対象に応じてimg2imgとinpaintを使い分ける。

顔・手など:
    元画像 + マスク + inpaint

ポーズ・画風・キャラクター全体:
    元画像 + img2img

修正結果の採用可否は、このサービスだけで決めず、
ConsistencyService / RepairLoopService側で検証する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ai.image.generation_request import GenerationRequest


class ImageRepairService:
    """画像の修正処理を統括するサービス。"""

    # マスクを使って修正したい対象
    INPAINT_CATEGORIES = {
        "face",
        "hands",
        "hand",
        "eyes",
        "mouth",
        "details",
        "detail",
    }

    # 元画像を参考に再生成したい対象
    IMG2IMG_CATEGORIES = {
        "character",
        "pose",
        "style",
        "body",
        "clothing",
        "color",
        "shading",
    }

    def __init__(
        self,
        image_provider: Any,
        region_detector: Any,
        request_factory: Any,
    ) -> None:
        """
        Args:
            image_provider:
                ComfyUIImageProviderなど。

            region_detector:
                detect(image_path, category)で
                修正領域のマスクを検出するコンポーネント。

            request_factory:
                修正用GenerationRequestを作るコンポーネント。
                呼び出し側で既存のRequest生成処理を渡す。
        """
        self.image_provider = image_provider
        self.region_detector = region_detector
        self.request_factory = request_factory

    def repair_category(
        self,
        image_path: str | Path,
        category: str,
        prompt: str,
        negative_prompt: str = "",
        mask_path: Optional[str | Path] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """
        指定されたカテゴリの修正を実行する。

        このメソッドは修正画像を生成するところまでを担当する。
        元画像より良くなったかどうかは別途検証する。
        """
        source = Path(image_path)

        if not source.is_file():
            return self._failure(
                "修正元の画像が見つかりません。",
                ["source_image_not_found"],
            )

        category = category.strip().lower()

        if not category:
            return self._failure(
                "修正カテゴリが指定されていません。",
                ["category_required"],
            )

        request = self._create_request(
            prompt=prompt,
            negative_prompt=negative_prompt,
            category=category,
            metadata=metadata or {},
        )

        if category in self.INPAINT_CATEGORIES:
            return self._repair_with_inpaint(
                source=source,
                category=category,
                request=request,
                mask_path=mask_path,
            )

        if category in self.IMG2IMG_CATEGORIES:
            return self._repair_with_img2img(
                source=source,
                category=category,
                request=request,
            )

        return self._failure(
            f"未対応の修正カテゴリです: {category}",
            ["unsupported_repair_category"],
            metadata={"category": category},
        )

    def _repair_with_inpaint(
        self,
        source: Path,
        category: str,
        request: GenerationRequest,
        mask_path: Optional[str | Path],
    ):
        """マスク領域を修正する。"""

        if mask_path is None:
            try:
                detected = self.region_detector.detect(
                    str(source),
                    category,
                )
            except Exception as exc:
                return self._failure(
                    "修正領域の検出に失敗しました。",
                    [f"{type(exc).__name__}: {exc}"],
                    metadata={"category": category},
                )

            # RegionDetectionProviderの戻り値は、
            # 実際の実装に合わせて調整する。
            if isinstance(detected, (str, Path)):
                mask_path = detected

            elif isinstance(detected, dict):
                mask_path = (
                    detected.get("mask_path")
                    or detected.get("path")
                )

            elif detected is not None:
                mask_path = getattr(
                    detected,
                    "mask_path",
                    None,
                )

        if not mask_path:
            return self._failure(
                "修正対象のマスクを取得できませんでした。",
                ["repair_mask_missing"],
                metadata={"category": category},
            )

        mask = Path(mask_path)

        if not mask.is_file():
            return self._failure(
                "修正用のマスクファイルが見つかりません。",
                ["mask_file_not_found"],
                metadata={"mask_path": str(mask)},
            )

        return self.image_provider.inpaint(
            source_image=str(source),
            mask_image=str(mask),
            request=request,
        )

    def _repair_with_img2img(
        self,
        source: Path,
        category: str,
        request: GenerationRequest,
    ):
        """元画像を参考に画像を再生成する。"""

        return self.image_provider.image_to_image(
            source_image=str(source),
            request=request,
        )

    def _create_request(
        self,
        prompt: str,
        negative_prompt: str,
        category: str,
        metadata: dict[str, Any],
    ) -> GenerationRequest:
        """
        プロジェクト側のRequest生成処理を呼び出す。

        request_factoryは、例えば次の情報を反映する:
        - 修正カテゴリ
        - 元画像を維持するための設定
        - denoise_strength
        - キャラクター設定
        - 修正対象の制約
        """
        return self.request_factory.create(
            prompt=prompt,
            negative_prompt=negative_prompt,
            metadata={
                **metadata,
                "repair_category": category,
            },
        )

    @staticmethod
    def _failure(
        message: str,
        errors: list[str],
        metadata: Optional[dict[str, Any]] = None,
    ):
        # 既存GenerationResultのフィールド定義に合わせる。
        from ai.image.generation_result import GenerationResult

        return GenerationResult(
            success=False,
            image_path=None,
            seed=None,
            model_name=None,
            message=message,
            errors=errors,
            metadata=metadata or {},
        )
```

### この設計の注意点

このコードでは、`request_factory.create()` が存在することを前提にしている。現在のプロジェクトにそのクラスやメソッドがない場合は、既存の `GenerationService` が持つリクエスト生成処理を使う形に変更しよう。

また、`inpaint` のマスク検出はまだ完成していない。`region_detector.detect()` がマスク画像を生成する仕組みを持っていなければ、別途実装が必要になる。

---

## 5. キャラクターの同一性を守るための修正条件を追加する

画像生成を繰り返すと、元の絵から少しずつ顔や髪型が変わることがある。

そこで、修正リクエストに「変更してよい部分」と「維持すべき部分」を明示する仕組みを設ける。

例えば、次のような設定だ
```

このクラスは設定を管理するためのものだ。**設定しただけでAIが顔や画風を完全に維持できるわけではない。** 実際の効果は、生成プロンプト、マスク、モデル、LoRA、ControlNetなどへの反映と、生成後の画像比較によって確かめる必要がある。

---

## 6. 次に実装する検証処理

ここまでで、画像生成と修正処理の入口を整理できた。

ただし、実用的なイラスト制作AIにするには、修正画像を作って終わりにしてはいけない。次は `ConsistencyService` と `RepairLoopService` を接続し、**修正前と修正後を比較して、悪化した画像を採用しない仕組み**を実装する必要がある。

目指す処理の流れは次のとおり。

```text
自分で描いたイラスト
        │
        ▼
修正対象を指定
「手だけ修正して」
        │
        ▼
RepairPlanner
        │
        ├─ 修正カテゴリを決める
        ├─ 維持条件を決める
        └─ 修正強度を決める
        │
        ▼
ImageRepairService
        │
        ├─ マスクを用意
        ├─ inpaintを実行
        └─ 修正画像を生成
        │
        ▼
ConsistencyService
        │
        ├─ キャラクターの同一性
        ├─ 顔・手の状態
        ├─ 画風・配色
        └─ 未修正領域の変化
        │
        ▼
RepairLoopService
        │
        ├─ 改善した → 採用候補
        ├─ 悪化した → 不採用
        └─ 不十分 → 条件を調整して再試行
```

### 今の段階で、まだ完成していない機能

| 機能            | 現状                               |
| ------------- | -------------------------------- |
| ComfyUIとの通信   | 前回のクライアント実装を土台にできる               |
| テキストからの画像生成   | ワークフローの設定と実環境での確認が必要             |
| img2img       | 対応するワークフローの作成・検証が必要              |
| inpaint       | マスク処理を含むワークフローの作成・検証が必要          |
| 修正対象の自動検出     | `RegionDetectionProvider` の実装が必要 |
| キャラクターの同一性の評価 | 画像分析モデルとの接続が必要                   |
| 修正結果の自動採否     | 検証基準と再試行処理の統合が必要                 |
| アニメーション生成     | 静止画の生成・修正が安定した後に進める              |

## 開発の優先順位

次は、**`ConsistencyService` を実際の画像分析モデルにつなぎ、修正前後の画像を比較する仕組み**を優先したい。

単純な類似度だけでは、顔が変わったことや、手の形が改善したことを正しく判定できない場合がある。そのため、全体の類似度だけでなく、顔・手・画風・配色などを個別に評価する構成が適している。

さらに、最初から大規模なアニメーション生成に進むのではなく、まずは自分のイラスト1枚について「元画像を読み込む → 指定箇所を修正する → 元画像と比較する → 良い結果だけ採用する」という一連の流れを完成させよう。

そこまで安定すれば、次にポーズを変えた画像を生成し、キャラクターの同一性を維持しながらアニメーション用のフレームを作る段階へ進められる。
