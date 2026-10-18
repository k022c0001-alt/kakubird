<!DOCTYPE html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>塾</title>
    <style>
      body { margin:0; background:#f4f8ff; font-family: "Hiragino Kaku Gothic ProN", sans-serif; color:#2a2a2a; }
      .container { max-width:1100px; margin:0 auto; padding:24px; }
      .hero { background: linear-gradient(135deg,#456ad8,#7ba7ff); color:white; padding:52px 24px; border-radius:18px; }
      .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap:18px; }
      .card { background:white; border-radius:16px; padding:20px; box-shadow:0 8px 24px rgba(0,0,0,.04); }
      form { display:grid; gap:12px; }
      input, select, button, textarea { width:100%; padding:12px; border-radius:10px; border:1px solid #dfe7ff; }
      .btn { background:#3d63d6; color:white; border:none; cursor:pointer; }
      @media print { .no-print { display:none !important; } }
    </style>
  </head>
  <body data-business-type="school" data-business-name="Aster Academy">
    <div class="container">
      <div class="hero no-print">
        <h1>Aster Academy</h1>
        <p>小学生〜高校生向けの学習支援・受験対策塾</p>
        <button class="btn" data-action="print">印刷</button>
      </div>

      <div class="section grid">
        <div class="card"><h3>コース</h3><ul><li>小学部</li><li>中学部</li><li>高校受験対策</li><li>英語・数学特訓</li></ul></div>
        <div class="card"><h3>対象</h3><p>小学生〜高校生</p></div>
        <div class="card"><h3>営業時間</h3><p>平日 16:00〜21:00 / 土曜 10:00〜17:00</p></div>
      </div>

      <div class="section card">
        <h3>体験授業予約</h3>
        <form data-reservation-form data-form-type="reservation">
          <input name="reservation_date" type="date" required />
          <select name="reservation_slot"></select>
          <input name="name" placeholder="お名前" required />
          <input name="student_age" placeholder="学年" required />
          <select name="course">
            <option>小学生向け</option>
            <option>中学生向け</option>
            <option>高校受験対策</option>
          </select>
          <button type="submit" class="btn">予約する</button>
        </form>
      </div>

      <div class="section card">
        <h3>お問い合わせ</h3>
        <form data-form-type="contact" data-submit-url="/api/contact" data-success-message="お問い合わせを受け付けました。">
          <input name="name" placeholder="保護者名" required />
          <input name="email" type="email" placeholder="メールアドレス" required />
          <input name="tel" type="tel" placeholder="電話番号" required />
          <textarea name="message" rows="5" placeholder="ご相談内容" required></textarea>
          <button type="submit" class="btn">送信する</button>
        </form>
      </div>
    </div>

    <script type="module" src="/backend/tools/js/index.js"></script>
  </body>
</html>
