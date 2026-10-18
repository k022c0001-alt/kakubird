/**
 * worksheet_engine.js
 * #app-config-data の問題JSONから「授業用プリント」「解答用紙」「模範解答ON/OFF」を自動描画するエンジン。
 * 問題を追加・修正したい場合は JSON の questions 配列を編集するだけでOK。
 */
(function () {
  const configEl = document.getElementById("app-config-data");
  const qContainer = document.getElementById("ws-questions-container");
  const sheetContainer = document.getElementById("ws-answer-sheet-container");
  const sheetBody = document.getElementById("ws-answer-sheet-body");
  const subjectEl = document.getElementById("ws-subject");
  const totalPtsEl = document.getElementById("ws-total-points");
  const toggleAnsBtn = document.getElementById("toggle-answers-btn");

  if (!configEl || !qContainer) return;
  let config = {};
  try {
    config = JSON.parse(configEl.textContent || "{}");
  } catch (e) {
    console.error("Worksheet JSON parse error", e);
  }

  const questions = Array.isArray(config.questions) ? config.questions : [];
  let showAnswers = false;

  if (subjectEl) {
    subjectEl.textContent = `${config.subject || "演習プリント"} （目安時間: ${config.timeLimitMinutes || 15}分）`;
  }
  const totalPoints = questions.reduce((acc, q) => acc + (Number(q.points) || 0), 0);
  if (totalPtsEl) totalPtsEl.textContent = String(totalPoints);

  function renderQuestions() {
    qContainer.innerHTML = "";
    sheetBody.innerHTML = "";

    questions.forEach((q, idx) => {
      const qNum = q.number || idx + 1;
      const card = document.createElement("div");
      card.className = "worksheet-q-card";

      let choicesHtml = "";
      if (Array.isArray(q.choices) && q.choices.length > 0) {
        choicesHtml = `<div style="display:flex; flex-wrap:wrap; gap:12px; margin-top:8px; font-size:14px;">
          ${q.choices.map((c) => `<span>${c}</span>`).join("")}
        </div>`;
      }

      const answerHtml = showAnswers
        ? `<div style="margin-top:10px; padding:10px; border-radius:6px; background:rgba(220,38,38,0.08); border-left:4px solid #dc2626;">
             <div class="worksheet-answer-text">【模範解答】 ${q.answer || ""}</div>
             <div style="font-size:12px; margin-top:4px;">解説: ${q.explanation || ""}</div>
           </div>`
        : `<div style="margin-top:10px; height:36px; border:1px dashed rgba(100,116,139,0.6); border-radius:4px; padding:6px; font-size:12px; opacity:0.6;">解答記入スペース</div>`;

      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; font-weight:bold;">
          <span>問 ${qNum}</span>
          <span style="font-size:12px; opacity:0.75;">（配点 ${q.points || 10}点）</span>
        </div>
        <div style="margin-top:6px; line-height:1.7;">${q.prompt || ""}</div>
        ${choicesHtml}
        ${answerHtml}
      `;
      qContainer.appendChild(card);

      // 解答用紙テーブル側の行生成
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight:bold; text-align:center;">問 ${qNum}</td>
        <td class="${showAnswers ? "worksheet-answer-text" : ""}" style="min-height:42px;">
          ${showAnswers ? q.answer || "" : "&nbsp;"}
        </td>
        <td style="text-align:center;">${q.points || 10} 点</td>
      `;
      sheetBody.appendChild(tr);
    });
  }

  document.querySelectorAll("[data-view-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-view-mode]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      const mode = btn.getAttribute("data-view-mode");
      if (mode === "answer_sheet") {
        qContainer.style.display = "none";
        sheetContainer.style.display = "block";
      } else {
        qContainer.style.display = "block";
        sheetContainer.style.display = "none";
      }
    });
  });

  if (toggleAnsBtn) {
    toggleAnsBtn.addEventListener("click", () => {
      showAnswers = !showAnswers;
      toggleAnsBtn.classList.toggle("is-active", showAnswers);
      renderQuestions();
    });
  }

  renderQuestions();
})();
