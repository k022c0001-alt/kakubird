/**
 * rule_guide_engine.js
 * #app-config-data のJSONを読み取り、ルール順クリック（順次ロック解除）を制御する軽量エンジン。
 */
(function () {
  const configEl = document.getElementById("app-config-data");
  const listEl = document.getElementById("guide-step-list");
  const fillEl = document.getElementById("guide-progress-fill");
  const statusEl = document.getElementById("guide-status-text");
  const resetBtn = document.getElementById("guide-reset-btn");

  if (!configEl || !listEl) return;
  let config = {};
  try {
    config = JSON.parse(configEl.textContent || "{}");
  } catch (e) {
    console.error("Failed to parse guide config", e);
  }

  const steps = Array.isArray(config.steps) ? config.steps : [];
  const completedIds = new Set();

  function isStepUnlocked(index) {
    if (config.mode !== "sequential") return true;
    if (index === 0) return true;
    const prevStep = steps[index - 1];
    return prevStep && completedIds.has(prevStep.id);
  }

  function render() {
    listEl.innerHTML = "";
    steps.forEach((step, idx) => {
      const unlocked = isStepUnlocked(idx);
      const completed = completedIds.has(step.id);

      const card = document.createElement("div");
      card.className = "guide-step-card" + (!unlocked ? " is-locked" : "") + (completed ? " is-completed" : "");

      const icon = completed ? "✅" : unlocked ? "🔓" : "🔒";
      card.innerHTML = `
        <div class="guide-step-header">
          <span>${icon} ${step.title}</span>
          <span style="font-size:12px; padding:2px 8px; border-radius:999px; border:1px solid currentColor;">${step.badge || ""}</span>
        </div>
        <div style="font-size:13px; margin-top:6px; opacity:0.85;">${step.summary || ""}</div>
        ${completed ? `<div class="guide-step-detail">${step.detail || ""}</div>` : ""}
      `;

      card.addEventListener("click", () => {
        if (!unlocked) {
          alert("⚠️ ルールにより、前のステップを先に完了させる必要があります！");
          return;
        }
        completedIds.add(step.id);
        render();
      });

      listEl.appendChild(card);
    });

    const pct = steps.length > 0 ? Math.round((completedIds.size / steps.length) * 100) : 0;
    if (fillEl) fillEl.style.width = pct + "%";
    if (statusEl) {
      statusEl.textContent =
        completedIds.size === steps.length && steps.length > 0
          ? config.completionMessage || "すべて完了しました！"
          : `進捗: ${completedIds.size} / ${steps.length} 完了 (${pct}%)`;
    }
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      completedIds.clear();
      render();
    });
  }

  render();
})();
