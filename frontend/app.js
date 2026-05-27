// ====== Config ======
const API_BASE = "https://equity-research-agent-0t0d.onrender.com";

// ====== DOM ======
const form = document.getElementById("analyze-form");
const tickerInput = document.getElementById("ticker-input");
const analyzeBtn = document.getElementById("analyze-btn");
const loadingEl = document.getElementById("loading");
const loadingStepEl = document.getElementById("loading-step");
const errorEl = document.getElementById("error");
const errorMsgEl = document.getElementById("error-msg");
const resultsEl = document.getElementById("results");

document.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
  tickerInput.value = c.dataset.ticker;
  form.requestSubmit();
}));

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const ticker = tickerInput.value.trim().toUpperCase();
  if (!ticker) return;
  await runAnalysis(ticker);
});

// ====== Loading animation ======
const steps = [
  { id: "step-1", text: "Pulling financials, news, peers from FMP...", delay: 0 },
  { id: "step-2", text: "Classifier picking the right valuation framework...", delay: 4000 },
  { id: "step-3", text: "5 research agents running in parallel...", delay: 9000 },
  { id: "step-4", text: "DCF + comps + scenarios triangulation...", delay: 22000 },
  { id: "step-5", text: "Bull vs bear advocates debating...", delay: 32000 },
  { id: "step-6", text: "Chief strategist writing the call...", delay: 42000 },
];

let stepTimers = [];

function startStepAnimation() {
  steps.forEach(s => {
    const el = document.getElementById(s.id);
    if (el) el.classList.remove("active", "done");
  });
  const first = document.getElementById(steps[0].id);
  if (first) first.classList.add("active");
  loadingStepEl.textContent = steps[0].text;

  for (let i = 1; i < steps.length; i++) {
    const t = setTimeout(() => {
      const prev = document.getElementById(steps[i - 1].id);
      const cur = document.getElementById(steps[i].id);
      if (prev) { prev.classList.remove("active"); prev.classList.add("done"); }
      if (cur) cur.classList.add("active");
      loadingStepEl.textContent = steps[i].text;
    }, steps[i].delay);
    stepTimers.push(t);
  }
}

function stopStepAnimation() {
  stepTimers.forEach(clearTimeout);
  stepTimers = [];
  steps.forEach(s => {
    const el = document.getElementById(s.id);
    if (el) { el.classList.remove("active"); el.classList.add("done"); }
  });
}

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

function fmt$(v, decimals = 2) {
  if (v == null || isNaN(v)) return "—";
  return "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function fmtMoneyShort(v) {
  if (v == null || isNaN(v)) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toLocaleString()}`;
}
function fmtPct(v, d = 1) {
  if (v == null || isNaN(v)) return "—";
  const n = Number(v) * 100;
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(d)}%`;
}

function bulletize(text) {
  if (!text) return "";
  const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
  const looksBulleted = lines.some(l => /^[-*•]\s|^\d+[.)]\s/.test(l));
  if (looksBulleted) {
    return "<ul>" + lines
      .map(l => l.replace(/^[-*•]\s*/, "").replace(/^\d+[.)]\s*/, ""))
      .filter(Boolean)
      .map(l => `<li>${escapeHtml(l)}</li>`)
      .join("") + "</ul>";
  }
  return lines.map(l => `<p>${escapeHtml(l)}</p>`).join("");
}

function paraize(text) {
  if (!text) return "";
  return text.split("\n\n").map(p => p.trim()).filter(Boolean).map(p => `<p>${escapeHtml(p)}</p>`).join("");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setEl(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function renderResults(d) {
  // Header
  setEl("r-ticker", d.ticker);
  setEl("r-name", d.company_name);
  setEl("r-sector", d.sector);

  const badge = document.getElementById("r-badge");
  badge.classList.remove("buy", "hold", "sell");
  badge.classList.add(d.recommendation.toLowerCase());
  setEl("r-rec", d.recommendation);

  // Classification strip
  setEl("r-type", d.stock_type || "—");
  setEl("r-framework", d.valuation_framework || "—");
  if (d.target_range_low && d.target_range_high) {
    document.getElementById("cs-range").style.display = "";
    setEl("r-range", `${fmt$(d.target_range_low, 0)} – ${fmt$(d.target_range_high, 0)}`);
  } else {
    document.getElementById("cs-range").style.display = "none";
  }

  // KPIs
  setEl("k-current", fmt$(d.current_price));
  setEl("k-target", fmt$(d.target_price));
  const upEl = document.getElementById("k-upside");
  upEl.textContent = fmtPct(d.upside_pct);
  upEl.style.color = d.upside_pct >= 0 ? "var(--green)" : "var(--red)";
  setEl("k-confidence", d.confidence_score ? `${d.confidence_score}/10` : "—");

  // Momentum
  const setMom = (id, val) => {
    const el = document.getElementById(id);
    el.classList.remove("positive", "negative");
    if (val == null) { el.textContent = "—"; return; }
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
  setHtml("r-summary", paraize(d.executive_summary));
  setHtml("r-thesis", bulletize(d.investment_thesis));
  setHtml("r-risks", bulletize(d.risks));
  setHtml("r-overview", paraize(d.business_overview));
  setHtml("r-moat", paraize(d.moat));
  setHtml("r-margin", paraize(d.margin_trajectory));
  setHtml("r-tech", paraize(d.technicals_read));
  setHtml("r-macro", paraize(d.macro_view));
  setHtml("r-bull", bulletize(d.bull_case));
  setHtml("r-bear", bulletize(d.bear_case));

  // What would change our mind
  const cmCard = document.getElementById("change-mind-card");
  const cmText = (d.what_would_change_mind || "").trim();
  if (cmText) {
    setEl("r-change-mind", cmText);
    cmCard.classList.remove("hidden");
  } else {
    cmCard.classList.add("hidden");
  }

  // Scenarios
  const scCard = document.getElementById("scenarios-card");
  const scenarios = d.scenarios || {};
  const scHasData = scenarios.bull || scenarios.base || scenarios.bear;
  if (scHasData) {
    const cells = ["bull", "base", "bear"].map(k => {
      const sc = scenarios[k] || {};
      if (!sc.price) return "";
      const upClass = sc.upside_pct >= 0 ? "positive" : "negative";
      return `<div class="scenario-cell ${k}">
        <div class="scenario-label">${k.toUpperCase()}</div>
        <div class="scenario-price">${fmt$(sc.price, 0)}</div>
        <div class="scenario-upside ${upClass}">${fmtPct(sc.upside_pct)}</div>
        <div class="scenario-desc">${escapeHtml(sc.description || "")}</div>
      </div>`;
    }).join("");
    setHtml("r-scenarios", cells);
    scCard.classList.remove("hidden");
  } else {
    scCard.classList.add("hidden");
  }

  // Bull/bear cards visibility
  document.getElementById("bull-card").style.display = d.bull_case ? "" : "none";
  document.getElementById("bear-card").style.display = d.bear_case ? "" : "none";

  // Catalysts
  const catCard = document.getElementById("catalysts-card");
  const cats = d.catalysts || [];
  if (cats.length) {
    const html = cats.map(c => `<div class="catalyst-item">
      <div class="catalyst-impact ${escapeHtml((c.impact||'watch').toLowerCase())}">${escapeHtml(c.impact || "WATCH")}</div>
      <div class="catalyst-text">
        <div class="catalyst-headline">${escapeHtml(c.headline || "")}</div>
        <div class="catalyst-interp">${escapeHtml(c.interpretation || "")}</div>
      </div>
    </div>`).join("");
    setHtml("r-catalysts", html);
    catCard.classList.remove("hidden");
  } else {
    catCard.classList.add("hidden");
  }

  // Peer table
  const peerCard = document.getElementById("peer-card");
  const peers = d.peer_table || [];
  if (peers.length) {
    const header = `<thead><tr><th>Ticker</th><th>Market Cap</th><th>P/E</th><th>EV/EBITDA</th><th>EV/Sales</th><th>P/B</th></tr></thead>`;
    const rows = peers.map(p => {
      const cls = p.is_subject ? "subject" : "";
      const fmt = v => (v != null) ? Number(v).toFixed(1) : "—";
      return `<tr class="${cls}">
        <td>${escapeHtml(p.ticker || "")}</td>
        <td>${fmtMoneyShort(p.market_cap)}</td>
        <td>${fmt(p.pe)}</td>
        <td>${fmt(p.ev_ebitda)}</td>
        <td>${fmt(p.ev_sales)}</td>
        <td>${fmt(p.pb)}</td>
      </tr>`;
    }).join("");
    setHtml("peer-table", `${header}<tbody>${rows}</tbody>`);
    setEl("r-peer-interp", d.peer_interpretation || "");
    peerCard.classList.remove("hidden");
  } else {
    peerCard.classList.add("hidden");
  }

  // Log
  setHtml("r-log", (d.log || []).map(l => `<li>${escapeHtml(l)}</li>`).join(""));

  resultsEl.classList.remove("hidden");
  resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}
