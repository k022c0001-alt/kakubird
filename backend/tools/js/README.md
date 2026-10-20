ビジネスタイプごとのプリセットを追加しました。

使い方:
1. HTML の <body> に data-business-type="massage" のように設定します。
2. 必要なら data-business-name="店舗名" を設定してページタイトルやサンプル商品名に反映します。

サポートされているタイプ:
- massage
- cafe
- bookstore
- rental
- beauty
- school
- bar
- medical
- landlord

例:
<body data-business-type="cafe" data-business-name="喫茶カクバード">
  <div data-services></div>
  <form data-reservation-form data-form-type="reservation">
    <input name="reservation_date" type="date" />
    <select name="reservation_slot"></select>
    <button type="submit">予約する</button>
  </form>
</body>
