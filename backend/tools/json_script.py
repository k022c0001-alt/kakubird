Bash
pip install google-generativeai openai
統合版スクリプト
Python
import json
import os
import re
from pathlib import Path

# APIごとの処理を分岐するための統合関数
def generate_json_content(prompt: str, provider: str) -> str:
    if provider == "gemini":
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEYが設定されていません。")
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content(prompt)
        return response.text

    elif provider in ["groq", "openrouter", "mistral"]:
        from openai import OpenAI
        
        # プロバイダーごとの設定
        if provider == "groq":
            api_key = os.environ.get("GROQ_API_KEY")
            base_url = "https://api.groq.com/openai/v1"
            model_name = "llama3-8b-8192"  # 高速＆JSONモード対応モデル
        elif provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            base_url = "https://openrouter.ai/api/v1"
            model_name = "google/gemma-2-9b-it:free"  # 無料枠の高性能モデル例
        elif provider == "mistral":
            api_key = os.environ.get("MISTRAL_API_KEY")
            base_url = "https://api.mistral.ai/v1"
            model_name = "mistral-large-latest" # Mistral APIの最新モデル
            
        if not api_key:
            raise ValueError(f"{provider.upper()}_API_KEYが設定されていません。")

        client = OpenAI(api_key=api_key, base_url=base_url)

        # 共通のAPIコール (JSONモード指定)
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    else:
        raise ValueError(f"未対応のプロバイダーです: {provider}")


JSON_SCHEMA_PROMPT = """
あなたはVS Codeの専門家であり、ナレッジベースの構築者です。
入力されたテキストを分析し、以下のJSONスキーマに従って必ず有効なJSON形式で検索用メタデータとコンテンツを生成してください。

【出力フォーマット】
{
  "name": "タイトル（簡潔に）",
  "description": "内容の短い説明（1〜2文）",
  "category": "vscode_guide",
  "domain": {
    "primary": "ide",
    "secondary": ["editor", "vscode", "関連する機能名など"]
  },
  "retrieval": {
    "keywords": ["検索されやすい単語", "類義語", "英語名"],
    "intents": ["ユーザーが何をしたい時にこの情報が必要になるか（例: 画面を分割したい）"],
    "tags": ["vscode", "関連タグ"],
    "technologies": ["VS Code"],
    "message_examples": [
      "ユーザーが実際にチャットに入力しそうな質問文1",
      "ユーザーが実際にチャットに入力しそうな質問文2"
    ],
    "weight": 1.0,
    "priority": 1.0
  },
  "content": {
    "summary": "要約",
    "details": "テキストの主要な情報をMarkdown形式で整理した詳細内容"
  }
}
"""

def chunk_text_by_paragraphs(text: str, max_chars: int = 1500) -> list[str]:
    """テキストを段落（空行）ごとに分割し、指定した文字数に収まるように結合してチャンクを作成する。"""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current_chunk = []
    current_length = 0

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        
        if current_length + len(p) > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [p]
            current_length = len(p)
        else:
            current_chunk.append(p)
            current_length += len(p)
            
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
        
    return chunks

def process_text_to_json(input_text: str, output_dir: str, provider: str = "gemini"):
    """テキストをチャンクに分割し、指定したAPIプロバイダーを使用してJSON化して保存する"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"使用API: {provider.upper()}")
    print("テキストを分割しています...")
    chunks = chunk_text_by_paragraphs(input_text)
    print(f"合計 {len(chunks)} 個のチャンクに分割しました。")

    for i, chunk in enumerate(chunks, 1):
        print(f"チャンク {i}/{len(chunks)} を処理中...")
        
        prompt = f"{JSON_SCHEMA_PROMPT}\n\n【入力テキスト】\n{chunk}"
        
        try:
            # API切り替え関数を呼び出す
            response_text = generate_json_content(prompt, provider)
            
            # 文字列として返ってきたJSONを辞書にパースして検証
            json_data = json.loads(response_text)
            
            # ファイル名の安全な作成
            safe_name = re.sub(r'[\\/*?:"<>|]', "", json_data.get("name", f"chunk_{i}"))
            safe_name = safe_name.replace(" ", "_")
            file_name = f"{i:03d}_{safe_name}.json"
            
            with open(output_path / file_name, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
                
            print(f"  -> 保存完了: {file_name}")
            
        except json.JSONDecodeError as e:
            print(f"  -> JSONパースエラーが発生しました: {e}\n[APIからの生の返答]:\n{response_text[:200]}...")
        except Exception as e:
            print(f"  -> エラーが発生しました: {e}")

if __name__ == "__main__":
    # 環境変数の設定例（実際はターミナルや.env等で設定してください）
    # os.environ["GEMINI_API_KEY"] = "your-gemini-key"
    # os.environ["GROQ_API_KEY"] = "your-groq-key"
    # os.environ["OPENROUTER_API_KEY"] = "your-openrouter-key"
    # os.environ["MISTRAL_API_KEY"] = "your-mistral-key"

    sample_text = """
    VS Codeの拡張機能について
    VS Codeの真の力は拡張機能（Extensions）にあります。画面左側の四角いアイコンをクリックするか、Ctrl+Shift+Xを押すことで拡張機能ビューを開くことができます。
    
    おすすめの拡張機能
    1. Prettier - コードフォーマッター。保存時に自動でインデントや改行を整えてくれます。
    2. Python - Python開発に必須。デバッグや補完を強力にサポートします。
    3. GitLens - Gitの履歴や誰がその行を書いたかをエディタ上で可視化してくれます。
    
    拡張機能の探し方
    検索ボックスにキーワードを入れるだけでなく、「@category:linters」のようにフィルタを使って検索することも可能です。
    """
    
    # 実行プロバイダーを選択: "gemini", "groq", "openrouter", "mistral"
    SELECTED_PROVIDER = "groq" 
    
    # 実行
    process_text_to_json(sample_text, output_dir="./vscode_knowledge_json", provider=SELECTED_PROVIDER)
