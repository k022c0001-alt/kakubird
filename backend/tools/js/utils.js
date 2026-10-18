# Kakubird HTML Tools

このフォルダは、Gemini で生成した HTML をそのまま使いながら、後から編集・拡張しやすくするための JavaScript ツール群です。

## 使い方

HTML の末尾で次を読み込んでください。

```html
<script type="module" src="/backend/tools/js/index.js"></script>
```

## 主要な機能

- 印刷対応: `data-action="print"` を付けたボタンで印刷
- PDF 配布: 印刷ダイアログを起動して PDF 保存に対応
- Excel/CSV エクスポート: `data-export-target` と `data-export-type` を使う
- 問い合わせフォーム: `data-form-type` で validation と送信を自動化
- 予約フォーム: 日付に応じて時間帯を自動更新
- 商品管理: localStorage を使った簡易カート
- 教員向けプリント: `data-page-type="lesson"` と `data-print-type="test"` などでレイアウト切替

## 例

```html
<body data-page-type="lesson" data-print-type="test" data-page-title="英語テストプリント">
  <button data-action="print">印刷</button>
  <button data-export-target="#worksheet-table" data-export-type="csv" data-filename="worksheet.csv">Excel出力</button>

  <form data-form-type="contact" data-submit-url="/api/contact" data-success-message="お問い合わせを受け付けました。">
    <input type="text" name="name" required />
    <input type="email" name="email" required />
    <textarea name="message" required></textarea>
    <button type="submit">送信</button>
  </form>
</body>
```

## ページ種別

以下の値が使えます。

- `lesson`
- `test`
- `answer`
- `report`
- `contact`
- `reservation`
- `presentation`
- `shop`
- `public`

## 追加するときのルール

- HTML はレイアウトやコンテンツに集中する
- JavaScript は機能ごとに分割する
- UI だけを差し替えたい場合は `data-*` 属性で制御する
- Gemini �� HTML を再生成しても、JS の構造はほぼ維持できる

## 今後の拡張候補

- 先生向けのテスト採点支援
- オンライン授業の発表スライド制御
- 予約システムのカレンダー連携
- ネットショップの在庫管理連携
- PDF 変換用のサーバー側 API 連携
