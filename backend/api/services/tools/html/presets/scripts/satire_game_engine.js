/**
 * satire_game_engine.js
 * Ollama不使用・完全ルールベース＆データ駆動型の「一撃スコア算出＆ガチャシミュレーター」エンジン
 *
 * 【仕様】
 * - ステージは「STAGE 1」で固定（パズル操作なし）
 * - ガチャを回すたびに 1〜4000 のスコアがベーススコアに加算される
 * - 特殊能力「最終スコア1.5倍」を持つキャラを1体だけ編成（連れていく）可能
 * - 「STAGE 1 に出撃（ワンクリック一撃スコア算出）」を押すと、
 *   [ガチャ累計ベーススコア] × [同行キャラ倍率(1.5倍 or 1.0倍)] が一気に算出・演出表示される
 */
(function () {
  const configEl = document.getElementById("app-config-data");
  if (!configEl) return;

  let config = {};
  try {
    config = JSON.parse(configEl.textContent || "{}");
  } catch (e) {
    console.error("Failed to parse game simulator config:", e);
  }

  // ゲーム状態
  let baseGachaScore = Number(config.initialBaseScore) || 0;
  let totalPulls = 0;
  let virtualYenSpent = 0;
  let lastAddedScore = 0;
  let lastFinalScore = 0;
  let highScore = 0;

  // 同行キャラ一覧と現在の編成（1体のみ）
  const companions = Array.isArray(config.companions) && config.companions.length > 0
    ? config.companions
    : [
        {
          id: "none",
          name: "同行キャラなし（ソロ出撃）",
          abilityName: "特殊能力なし",
          multiplier: 1.0,
          unlocked: true,
          badge: "初期"
        },
        {
          id: "empress_15x",
          name: "【覇権SSR】祝祭のスコアエンプレス",
          abilityName: "特殊能力：最終スコア 1.5倍 ブースト",
          multiplier: 1.5,
          unlocked: true,
          badge: "最終1.5倍"
        },
        {
          id: "cyber_diva_15x",
          name: "【限定UR】ネオン・オーバーロード",
          abilityName: "特殊能力：最終スコア 1.5倍 シンクロ",
          multiplier: 1.5,
          unlocked: false,
          badge: "ガチャ排出・最終1.5倍"
        }
      ];

  // デフォルトで1.5倍キャラが解放済みなら選択可能、初期選択は config.defaultCompanionId または empress_15x
  let selectedCompanionId = config.defaultCompanionId || "empress_15x";

  // DOM要素の取得
  const stageBadgeEl = document.getElementById("sim-stage-badge");
  const baseScoreEl = document.getElementById("sim-base-score");
  const lastAddEl = document.getElementById("sim-last-add");
  const multValEl = document.getElementById("sim-multiplier-val");
  const finalScoreEl = document.getElementById("sim-final-score");
  const formulaEl = document.getElementById("sim-score-formula");
  const pullsEl = document.getElementById("sim-pull-count");
  const yenEl = document.getElementById("sim-yen-spent");
  const companionListEl = document.getElementById("sim-companion-list");
  const logBoxEl = document.getElementById("sim-log-box");
  const burstBannerEl = document.getElementById("sim-burst-banner");

  const gachaSingleBtn = document.getElementById("sim-gacha-single-btn");
  const gachaTenBtn = document.getElementById("sim-gacha-ten-btn");
  const attackBtn = document.getElementById("sim-oneclick-attack-btn");
  const resetBtn = document.getElementById("sim-reset-btn");

  const minRoll = Number(config.gachaScoreMin) || 1;
  const maxRoll = Number(config.gachaScoreMax) || 4000;
  const pullCostYen = Number(config.singlePullCostYen) || 300;

  function getSelectedCompanion() {
    return companions.find((c) => c.id === selectedCompanionId && c.unlocked) || companions[0];
  }

  function randomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  }

  function addLog(message, highlight) {
    if (!logBoxEl) return;
    const item = document.createElement("div");
    item.style.padding = "4px 0";
    item.style.borderBottom = "1px dashed rgba(148, 163, 184, 0.2)";
    if (highlight) {
      item.style.color = "#38bdf8";
      item.style.fontWeight = "bold";
    }
    item.textContent = message;
    logBoxEl.prepend(item);
  }

  function renderCompanions() {
    if (!companionListEl) return;
    companionListEl.innerHTML = "";

    companions.forEach((comp) => {
      const isSelected = comp.id === selectedCompanionId;
      const card = document.createElement("button");
      card.type = "button";
      card.className = "sim-companion-card" + (isSelected ? " is-selected" : "") + (!comp.unlocked ? " is-locked" : "");
      card.disabled = !comp.unlocked;

      const statusIcon = !comp.unlocked ? "🔒 未所持" : isSelected ? "✅ 同行中 (1体枠)" : "待機中";
      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
          <span style="font-weight:800; font-size:14px;">${comp.name}</span>
          <span class="sim-comp-badge">${statusIcon}</span>
        </div>
        <div style="font-size:12px; margin-top:4px; opacity:0.9; text-align:left;">
          🌟 ${comp.abilityName} （倍率: <strong>×${comp.multiplier.toFixed(1)}</strong>）
        </div>
      `;

      card.addEventListener("click", () => {
        if (!comp.unlocked) return;
        selectedCompanionId = comp.id;
        addLog(`👯 同行キャラを「${comp.name}」（最終スコア ×${comp.multiplier.toFixed(1)}）に変更しました。`, false);
        renderCompanions();
        updateUI();
      });

      companionListEl.appendChild(card);
    });
  }

  function updateUI() {
    const comp = getSelectedCompanion();
    const mult = Number(comp.multiplier) || 1.0;
    const previewFinal = Math.floor(baseGachaScore * mult);

    if (stageBadgeEl) {
      stageBadgeEl.textContent = "STAGE 1 (固定・ワンクリック決戦)";
    }
    if (baseScoreEl) {
      baseScoreEl.textContent = baseGachaScore.toLocaleString();
    }
    if (lastAddEl) {
      lastAddEl.textContent = lastAddedScore > 0 ? `+${lastAddedScore.toLocaleString()} pt` : "+0 pt";
    }
    if (multValEl) {
      multValEl.textContent = `×${mult.toFixed(1)}`;
    }
    if (pullsEl) {
      pullsEl.textContent = `${totalPulls} 回`;
    }
    if (yenEl) {
      yenEl.textContent = `¥${virtualYenSpent.toLocaleString()}`;
    }
    if (formulaEl) {
      formulaEl.textContent = `計算式: ベース ${baseGachaScore.toLocaleString()} × 同行倍率 ${mult.toFixed(1)} = 予測 ${previewFinal.toLocaleString()} pt`;
    }
  }

  function executeGacha(count) {
    let sumAdded = 0;
    let maxSingle = 0;

    for (let i = 0; i < count; i++) {
      totalPulls++;
      virtualYenSpent += pullCostYen;
      const roll = randomInt(minRoll, maxRoll);
      sumAdded += roll;
      if (roll > maxSingle) maxSingle = roll;

      // 高スコア(3500以上)を引いたときに未解放の1.5倍キャラがいれば解放
      if (roll >= 3500) {
        const lockedComp = companions.find((c) => !c.unlocked);
        if (lockedComp) {
          lockedComp.unlocked = true;
          selectedCompanionId = lockedComp.id;
          addLog(`🎊 虹演出！高スコア枠(${roll}pt)と同時に新1.5倍キャラ「${lockedComp.name}」を解放＆編成しました！`, true);
          renderCompanions();
        }
      }
    }

    baseGachaScore += sumAdded;
    lastAddedScore = sumAdded;

    if (count === 1) {
      const rank = sumAdded >= 3000 ? "🌈【大当たり！】" : sumAdded >= 1500 ? "✨【好調】" : "🎲";
      addLog(`${rank} 単発ガチャ結果: +${sumAdded.toLocaleString()} スコア加算！（現在ベース: ${baseGachaScore.toLocaleString()} pt）`, sumAdded >= 3000);
    } else {
      addLog(`💎 ${count}連ガチャ結果: 合計 +${sumAdded.toLocaleString()} スコア加算！（最大単発: +${maxSingle.toLocaleString()} pt / 現在ベース: ${baseGachaScore.toLocaleString()} pt）`, true);
    }

    updateUI();
  }

  function executeInstantStageAttack() {
    const comp = getSelectedCompanion();
    const mult = Number(comp.multiplier) || 1.0;
    lastFinalScore = Math.floor(baseGachaScore * mult);
    if (lastFinalScore > highScore) {
      highScore = lastFinalScore;
    }

    if (finalScoreEl) {
      finalScoreEl.textContent = lastFinalScore.toLocaleString();
      finalScoreEl.classList.remove("sim-pop-anim");
      void finalScoreEl.offsetWidth; // reflow
      finalScoreEl.classList.add("sim-pop-anim");
    }

    if (burstBannerEl) {
      burstBannerEl.style.display = "block";
      burstBannerEl.innerHTML = `
        💥 <strong>STAGE 1 一撃フィニッシュ！</strong><br>
        ガチャ累計 <strong>${baseGachaScore.toLocaleString()}</strong> pt × <strong>${comp.name} (${mult.toFixed(1)}倍)</strong>
        ＝ 最終スコア <span style="font-size:22px; color:#facc15; font-weight:900;">${lastFinalScore.toLocaleString()}</span> pt 達成！！
      `;
    }

    addLog(
      `🚀 [STAGE 1 一撃算出] ベース ${baseGachaScore.toLocaleString()} × ${mult.toFixed(1)}倍 (${comp.name}) = 最終スコア ${lastFinalScore.toLocaleString()} pt！`,
      true
    );
    updateUI();
  }

  if (gachaSingleBtn) {
    gachaSingleBtn.addEventListener("click", () => executeGacha(1));
  }
  if (gachaTenBtn) {
    gachaTenBtn.addEventListener("click", () => executeGacha(10));
  }
  if (attackBtn) {
    attackBtn.addEventListener("click", executeInstantStageAttack);
  }
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      baseGachaScore = 0;
      totalPulls = 0;
      virtualYenSpent = 0;
      lastAddedScore = 0;
      lastFinalScore = 0;
      if (finalScoreEl) finalScoreEl.textContent = "0";
      if (burstBannerEl) burstBannerEl.style.display = "none";
      addLog("🔄 スコアとガチャ履歴をリセットしました。", false);
      updateUI();
    });
  }

  renderCompanions();
  updateUI();
})();
