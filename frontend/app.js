// ====== Config ======
// When running locally: backend on :8000
// When deployed: change this to your backend URL (e.g. https://your-app.onrender.com)
const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? "http://localhost:8000"
  : (window.__API_BASE__ || "");  // set window.__API_BASE__ via env at deploy time

// ====== DOM ======
const form = document.getElementById("analyze-form");
const tickerInput = document.getElementById("ticker-input");
const analyzeBtn = document.getElementById("analyze-btn");
const loadingEl = document.getElementById("loading");
const loadingStepEl = document.getElementById("loading-step");
const errorEl = document.getElementById("error");
const errorMsgEl = document.getElementById("error-msg");
const resultsEl = document.getElementById("results");

const chips = document.querySelectorAll(".chip");
chips.forEach(c => c.addEventListener("click", () => {
  tickerInput.value = c.dataset.ticker;
  form.requestSubmit();
}));

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const ticker = tickerInput.value.trim().toUpperCase();
  if (!ticker) return;
  await runAnalysis(ticker);
});

// ====== Loading step animation ======
const steps = [
  { id: "step-1", text: "Collecting financial data from Yahoo Finance...", delay: 0 },
  { id: "step-2", text: "Gemini analyzing business model and risks...", delay: 6000 },
  { id: "step-3", text: "Building DCF valuation model...", delay: 14000 },
  { id: "step-4", text: "Writing executive summary and recommendation...", delay: 22000 },
];

let stepTimers = [];

function startStepAnimation() {
  // Reset
  steps.forEach(s => {
    const el = document.getElementById(s.id);
    el.classList.remove("active", "done");
  });
  // Activate first
  document.getElementById(steps[0].id).classList.add("active");
  loadingStepEl.textContent = steps[0].text;

  for (let i = 1; i < steps.length; i++) {
    const t = setTimeout(() => {
      document.getElementById(steps[i - 1].id).classList.remove("active");
      document.getElementById(steps[i - 1].id).classList.add("done");
      document.getElementById(steps[i].id).classList.add("active");
      loadingStepEl.textContent = steps[i].text;
    }, steps[i].delay);
    stepTimers.push(t);
  }
}

function stopStepAnimation() {
  stepTimers.forEach(clearTimeout);
  stepTimers = [];
  steps.forEach(s => {
    document.getElementById(s.id).classList.remove("active");
    document.getElementById(s.id).classList.add("done");
  });
}

// ====== Main flow ======
async function runAnalysis(ticker) {
  errorEl.classList.add("hidden");
  resultsEl.classList.add("hidden");
  loadingEl.classList.remove("hidden");
  analyzeBtn.disabled = true;
  document.getElementById("loading-title").textContent = `Analyzing ${ticker}...`;
  startStepAnimation();

  try {
    const res = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed with status ${res.status}`);
    }

    const data = await res.json();
    stopStepAnimation();
    loadingEl.classList.add("hidden");
    renderResults(data);
  } catch (err) {
    stopStepAnimation();
    loadingEl.classList.add("hidden");
    showError(err.message || "Something went wrong.");
  } finally {
    analyzeBtn.disabled = false;
  }
}

function showError(msg) {
  errorMsgEl.textContent = msg;
  errorEl.classList.remove("hidden");
}

// ====== Render ======
function fmt$(v, decimals = 2) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return "$" + Number(v).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtPct(v, decimals = 1) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const n = Number(v) * 100;
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(decimals)}%`;
}

function bulletize(text) {
  if (!text) return "";
  const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
  // Detect if it's already bulleted
  const looksBulleted = lines.some(l => /^[-*•]\s|^\d+[.)]\s/.test(l));
  if (looksBulleted) {
    const items = lines
      .map(l => l.replace(/^[-*•]\s*/, "").replace(/^\d+[.)]\s*/, ""))
      .filter(Boolean)
      .map(l => `<li>${escapeHtml(l)}</li>`)
      .join("");
    return `<ul>${items}</ul>`;
  }
  return lines.map(l => `<p>${escapeHtml(l)}</p>`).join("");
}

function paraize(text) {
  if (!text) return "";
  return text.split("\n\n")
    .map(p => p.trim()).filter(Boolean)
    .map(p => `<p>${escapeHtml(p)}</p>`).join("");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderResults(d) {
  // Header
  document.getElementById("r-ticker").textContent = d.ticker;
  document.getElementById("r-name").textContent = d.company_name;
  document.getElementById("r-sector").textContent = d.sector;

  const badge = document.getElementById("r-badge");
  badge.classList.remove("buy", "hold", "sell");
  badge.classList.add(d.recommendation.toLowerCase());
  document.getElementById("r-rec").textContent = d.recommendation;

  // KPIs
  document.getElementById("k-current").textContent = fmt$(d.current_price);
  document.getElementById("k-target").textContent = fmt$(d.target_price);
  document.getElementById("k-upside").textContent = fmtPct(d.upside_pct);
  document.getElementById("k-upside").style.color =
    d.upside_pct >= 0 ? "var(--green)" : "var(--red)";

  // Confidence
  const confEl = document.getElementById("k-confidence");
  if (d.confidence_score) {
    confEl.textContent = `${d.confidence_score}/10`;
  } else {
    confEl.textContent = "—";
  }

  // Momentum strip
  const setMom = (id, val) => {
    const el = document.getElementById(id);
    el.classList.remove("positive", "negative");
    if (val === null || val === undefined) {
      el.textContent = "—";
      return;
    }
    el.textContent = fmtPct(val);
    el.classList.add(val >= 0 ? "positive" : "negative");
  };
  const m = d.momentum || {};
  setMom("m-1mo", m.price_1mo_pct);
  setMom("m-3mo", m.price_3mo_pct);
  setMom("m-ytd", m.price_ytd_pct);
  setMom("m-1yr", m.price_1yr_pct);

  // Downloads
  document.getElementById("d-pdf").href = `${API_BASE}/api/report/${d.job_id}`;
  document.getElementById("d-deck").href = `${API_BASE}/api/deck/${d.job_id}`;
  document.getElementById("d-model").href = `${API_BASE}/api/model/${d.job_id}`;

  // Prose
  document.getElementById("r-summary").innerHTML = paraize(d.executive_summary);
  document.getElementById("r-thesis").innerHTML = bulletize(d.investment_thesis);
  document.getElementById("r-risks").innerHTML = bulletize(d.risks);
  document.getElementById("r-overview").innerHTML = paraize(d.business_overview);
  document.getElementById("r-competitive").innerHTML = paraize(d.competitive_position);

  // What would change our mind
  const cmCard = document.getElementById("change-mind-card");
  const cmText = (d.what_would_change_mind || "").trim();
  if (cmText) {
    document.getElementById("r-change-mind").textContent = cmText;
    cmCard.classList.remove("hidden");
  } else {
    cmCard.classList.add("hidden");
  }

  // Catalysts
  const catCard = document.getElementById("catalysts-card");
  const catList = d.catalysts || [];
  if (catList.length > 0) {
    const html = catList.map(c => {
      const impact = (c.impact || "WATCH").toLowerCase();
      return `<div class="catalyst-item">
        <div class="catalyst-impact ${escapeHtml(impact)}">${escapeHtml(c.impact || "WATCH")}</div>
        <div class="catalyst-text">
          <div class="catalyst-headline">${escapeHtml(c.headline || "")}</div>
          <div class="catalyst-interp">${escapeHtml(c.interpretation || "")}</div>
        </div>
      </div>`;
    }).join("");
    document.getElementById("r-catalysts").innerHTML = html;
    catCard.classList.remove("hidden");
  } else {
    catCard.classList.add("hidden");
  }

  // Log
  const logEl = document.getElementById("r-log");
  logEl.innerHTML = (d.log || []).map(line => `<li>${escapeHtml(line)}</li>`).join("");

  resultsEl.classList.remove("hidden");
  resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}
