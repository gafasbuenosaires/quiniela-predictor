const API = "";
const APP_KEY = "quiniela_app_password";
const DIGIT_COLORS = {
  0: "#94a3b8",
  1: "#f472b6",
  2: "#60a5fa",
  3: "#a78bfa",
  4: "#34d399",
  5: "#fbbf24",
  6: "#fb923c",
  7: "#f87171",
  8: "#2dd4bf",
  9: "#e879f9",
};

const DRAW_NAMES = {
  primera: "Primera 12:00",
  matutina: "Matutina 15:00",
  vespertina: "Vespertina 18:00",
  nocturna: "Nocturna 21:00",
};

const DRAW_LABEL = {
  primera: "Primera",
  matutina: "Matutina",
  vespertina: "Vespertina",
  nocturna: "Nocturna",
};

let config = { poll_seconds: 120, provinces: [], default_province: "nacional" };
let currentProvince = null;
let pollTimer = null;
let syncTimer = null;
let countdownTimer = null;
let drawSyncTimer = null;
let syncing = false;
let currentNextDraw = null;
let drawSyncStatus = [];
let lastDrawResultsHash = "";

const $ = (id) => document.getElementById(id);

const SCHEDULE_STATUS = {
  done: { label: "Ya salio", cls: "done" },
  next: { label: "Proximo", cls: "next" },
  pending: { label: "Pendiente", cls: "pending" },
  live: { label: "En curso", cls: "live" },
  waiting: { label: "Esperando", cls: "waiting" },
};

function drawTimeLabel(id, hour, minute) {
  const fromConfig = (config.draw_times || []).find((d) => d.id === id);
  if (fromConfig?.time) return fromConfig.time;
  const m = minute ?? 0;
  return `${String(hour).padStart(2, "0")}:${String(m).padStart(2, "0")} hs`;
}

function formatCountdown(seconds, live) {
  if (live) return "Sorteo en curso — ventana activa";
  if (seconds <= 0) return "Ahora";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `Faltan ${h} h ${m} min`;
  if (m > 0) return `Faltan ${m} min ${s} seg`;
  return `Faltan ${s} seg`;
}

function renderDrawSchedule(nextInfo) {
  currentNextDraw = nextInfo;
  const grid = $("drawSchedule");
  const sub = $("scheduleSubtitle");
  const heroCountdown = $("nextDrawCountdown");
  if (!grid || !nextInfo) return;

  const nextId = nextInfo.next_draw;
  const schedule = (nextInfo.schedule || []).map((row) => ({
    ...row,
    status:
      row.id === nextId && row.status !== "done"
        ? row.status === "live"
          ? "live"
          : "next"
        : row.status,
  }));

  if (sub) {
    const dateLabel = nextInfo.is_today !== false ? "hoy" : nextInfo.target_date;
    sub.textContent =
      `Proximo sorteo: ${nextInfo.next_draw_name} · ${nextInfo.next_draw_time || ""} · ${dateLabel}`;
  }

  if (heroCountdown && nextInfo.draw_time) {
    const live = schedule.find((r) => r.id === nextId)?.status === "live";
    const secs = Math.max(0, Math.floor((new Date(nextInfo.draw_time) - new Date()) / 1000));
    heroCountdown.textContent = live
      ? "Sorteo en curso — ventana activa"
      : nextInfo.is_today === false
        ? nextInfo.countdown_label || formatCountdown(secs, false)
        : formatCountdown(secs, false);
    heroCountdown.classList.toggle("live", live);
  }

  grid.innerHTML = schedule
    .map((row) => {
      const st = SCHEDULE_STATUS[row.status] || SCHEDULE_STATUS.pending;
      const syncRow = (drawSyncStatus || []).find((s) => s.draw_type === row.id);
      let extra = "";
      if (syncRow?.has_result && syncRow.result_digit != null) {
        const c = DIGIT_COLORS[syncRow.result_digit] || "#3dd68c";
        extra = `<div class="schedule-result">Salio: <strong style="color:${c}">${syncRow.result_digit}</strong> <span class="muted">(${syncRow.result_number || ""})</span></div>`;
      } else if (syncRow?.phase === "waiting_sync") {
        extra = `<div class="schedule-result muted">Auto-sync ${syncRow.sync_at} hs</div>`;
      } else if (syncRow?.phase === "syncing") {
        extra = `<div class="schedule-result syncing">Actualizando resultado...</div>`;
      }
      return `
      <article class="schedule-card ${st.cls}">
        <div class="schedule-time">${row.time || drawTimeLabel(row.id, row.hour, row.minute)}</div>
        <div class="schedule-name">${row.name}</div>
        <span class="schedule-badge ${st.cls}">${st.label}</span>
        ${extra}
      </article>`;
    })
    .join("");

  startCountdownTimer();
}

function startCountdownTimer() {
  clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    if (!currentNextDraw?.draw_time) return;
    const el = $("nextDrawCountdown");
    if (!el) return;
    const drawAt = new Date(currentNextDraw.draw_time);
    const now = new Date();
    const endWindow = new Date(drawAt.getTime() + 30 * 60 * 1000);
    const secs = Math.max(0, Math.floor((drawAt - now) / 1000));
    const live = now >= drawAt && now < endWindow;
    if (live) {
      el.textContent = "Sorteo en curso — ventana activa";
    } else if (currentNextDraw.is_today === false && secs > 0) {
      el.textContent = `Manana ${currentNextDraw.next_draw_time} · ${formatCountdown(secs, false)}`;
    } else {
      el.textContent = formatCountdown(secs, false);
    }
    el.classList.toggle("live", live);
  }, 1000);
}

function renderNextDrawHeader(next) {
  if (!next) return;
  const time = next.next_draw_time || DRAW_NAMES[next.next_draw] || next.next_draw;
  $("nextDrawName").textContent =
    `${next.next_draw_name} · ${time} · ${next.target_date}`;
  renderDrawSchedule(next);
}


async function fetchJson(path, options = {}) {
  const headers = { ...authHeaders(), ...(options.headers || {}) };
  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (res.status === 401) {
    sessionStorage.removeItem(APP_KEY);
    showLogin("Clave incorrecta");
    throw new Error("Clave incorrecta");
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function authHeaders() {
  const pwd = sessionStorage.getItem(APP_KEY);
  return pwd ? { "X-App-Password": pwd } : {};
}

function showLogin(message = "") {
  const gate = $("loginGate");
  const err = $("loginError");
  if (gate) gate.classList.remove("hidden");
  if (err) {
    err.textContent = message || "Clave incorrecta";
    err.classList.toggle("hidden", !message);
  }
}

function hideLogin() {
  $("loginGate")?.classList.add("hidden");
  $("loginError")?.classList.add("hidden");
}

function setupLogin() {
  const form = $("loginForm");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const pwd = $("loginPassword").value.trim();
    sessionStorage.setItem(APP_KEY, pwd);
    try {
      const cfg = await fetchJson("/api/config");
      if (cfg.auth_required) hideLogin();
      await bootApp(cfg);
    } catch {
      sessionStorage.removeItem(APP_KEY);
      showLogin("Clave incorrecta");
    }
  });
}

function pct(n) {
  return `${(n * 100).toFixed(1)}%`;
}

function money(n) {
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 0,
  }).format(Number(n) || 0);
}

const PROVINCE_SHORT = {
  nacional: "Nacional",
  buenos_aires: "Provincia",
};

function renderActiveBets(bets) {
  const wrap = $("cajaActiveBets");
  if (!wrap) return;
  if (!bets?.length) {
    wrap.innerHTML = "<p class='muted'>Sin apuestas activas</p>";
    return;
  }
  wrap.innerHTML = bets
    .map((b) => {
      const color = DIGIT_COLORS[b.active_digit] || "#3dd68c";
      const threshold = b.double_threshold || 6;
      const pctStreak = Math.min(100, (b.loss_streak / threshold) * 100);
      return `
      <article class="caja-bet-card" data-province="${b.province}" data-draw="${b.draw_type}">
        <header class="caja-bet-head">
          <span class="caja-bet-prov">${b.province_label}</span>
          <span class="caja-bet-draw">${b.draw_name} · ${b.draw_time}</span>
        </header>
        <div class="caja-bet-digit-wrap">
          <label class="caja-bet-lbl">Numero jugado</label>
          <input type="number" class="caja-bet-digit" min="0" max="9" value="${b.active_digit}" style="color:${color}" />
        </div>
        <div class="caja-bet-meta">
          <div><span class="meta-lbl">Apuesta</span><strong class="caja-bet-stake">${money(b.stake)}</strong></div>
          <div><span class="meta-lbl">Si gana (x7)</span><strong class="win">${money(b.potential_win)}</strong></div>
        </div>
        <div class="caja-streak">
          <div class="caja-streak-top">
            <span>Fallos seguidos</span>
            <strong>${b.loss_streak} / ${threshold}</strong>
          </div>
          <div class="caja-streak-bar"><div class="caja-streak-fill" style="width:${pctStreak}%"></div></div>
          <p class="caja-streak-hint">${
            b.losses_to_double === 0
              ? `Proxima apuesta: ${money(b.next_stake_if_double)} (doble)`
              : `${b.losses_to_double} fallo(s) para doblar a ${money(b.next_stake_if_double)}`
          }</p>
        </div>
        <button type="button" class="btn primary sm btn-save-bet">Guardar numero</button>
      </article>`;
    })
    .join("");

  wrap.querySelectorAll(".caja-bet-digit").forEach((inp) => {
    inp.addEventListener("input", () => {
      inp.style.color = DIGIT_COLORS[Number(inp.value)] || "#fff";
    });
  });
  wrap.querySelectorAll(".btn-save-bet").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".caja-bet-card");
      saveSingleBet(card.dataset.province, card.dataset.draw, card);
    });
  });
}

async function saveSingleBet(province, drawType, card) {
  const digit = Number(card.querySelector(".caja-bet-digit").value);
  await fetchJson("/api/caja/slots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ province, draw_type: drawType, active_digit: digit }),
  });
  await loadCaja();
}

function renderCaja(state) {
  const c = state.caja || {};
  $("cajaInvertido").textContent = money(c.invertido);
  $("cajaGanado").textContent = money(c.ganado);
  $("cajaNeto").textContent = money(c.neto);
  $("cajaSaldo").textContent = money(c.saldo);
  if ($("cajaRule")) {
    const st = state.session?.status;
    $("cajaRule").textContent = st?.headline || state.session?.rule || "";
  }
  const statusEl = $("cajaSessionStatus");
  if (statusEl && state.session?.status) {
    statusEl.innerHTML = `
      <p>${state.session.status.nacional}</p>
      <p>${state.session.status.provincia}</p>`;
  }

  const s = state.settings || {};
  $("cajaInitial").value = s.initial_balance ?? 0;
  $("cajaDefaultStake").value = s.default_stake ?? 30000;
  $("cajaMultiplier").value = s.payout_multiplier ?? 7;
  $("cajaDoubleAfter").value = s.double_after_losses ?? 6;

  renderActiveBets(state.active_bets);

  const entries = state.entries || [];
  $("cajaLedgerStats").textContent =
    `${c.jugadas || 0} jugadas · ${c.aciertos || 0} aciertos · neto ${money(c.neto)}`;

  $("cajaLedgerBody").innerHTML = entries.length
    ? entries
        .map(
          (e) => `
      <tr class="${e.hit ? "hit-row" : ""}">
        <td>${e.draw_date}</td>
        <td>${DRAW_LABEL[e.draw_type] || e.draw_type}</td>
        <td>${PROVINCE_SHORT[e.province] || e.province}</td>
        <td><strong style="color:${DIGIT_COLORS[e.digit_played]}">${e.digit_played}</strong></td>
        <td><strong style="color:${DIGIT_COLORS[e.result_digit]}">${e.result_digit}</strong></td>
        <td>${money(e.stake)}</td>
        <td>${e.hit ? "✓ GANO" : "Perdio"}</td>
        <td class="win">${e.hit ? money(e.payout) : "—"}</td>
      </tr>`
        )
        .join("")
    : `<tr><td colspan="8" class="muted">Sin movimientos aun.</td></tr>`;
}

async function loadCaja() {
  const state = await fetchJson("/api/caja");
  renderCaja(state);
  setLastUpdate();
}

async function saveCajaSettings() {
  await fetchJson("/api/caja/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      initial_balance: Number($("cajaInitial").value),
      default_stake: Number($("cajaDefaultStake").value),
      payout_multiplier: Number($("cajaMultiplier").value),
      double_after_losses: Number($("cajaDoubleAfter").value),
    }),
  });
  await loadCaja();
}

async function processCaja() {
  const res = await fetchJson("/api/caja/process", { method: "POST" });
  renderCaja(res.state);
  if (res.result?.processed > 0) {
    $("cajaLedgerStats").textContent += ` · ${res.result.processed} procesados`;
  }
  setLastUpdate();
}

function styleMegaDigit(el, digit) {
  if (!el || digit === undefined || digit === null) return;
  const d = Number(digit);
  el.textContent = d;
  const color = DIGIT_COLORS[d] || "#3dd68c";
  el.style.color = color;
  el.style.borderColor = color;
  el.style.boxShadow = `0 0 80px ${color}99, 0 0 40px ${color}44`;
}

function renderPastDigits(container, digits) {
  if (!container) return;
  const list = (digits || []).slice(-8);
  if (!list.length) {
    container.innerHTML = '<span class="muted">Sin historial</span>';
    return;
  }
  container.innerHTML = list
    .map((d, i) => {
      const isLast = i === list.length - 1;
      const c = DIGIT_COLORS[d] || "#fff";
      return `<span class="past-chip ${isLast ? "last" : ""}" style="color:${c};border-color:${c}55">${d}</span>`;
    })
    .join("");
}

function renderOverviewMega(provinces) {
  const banner = $("overviewMega");
  const first = provinces.find((p) => p.has_data && p.expert_digit != null);
  if (!first) {
    banner.classList.add("hidden");
    return;
  }
  banner.classList.remove("hidden");
  banner.innerHTML = `
    <p class="mega-tag">Agente · ${first.name}</p>
    <h2 class="jugar-este">${first.play_message || "JUGA ESTE"}</h2>
    <p class="play-callout">${first.play_callout || ""}</p>
    <div class="antes-vs-pick">
      <div class="antes-block">
        <span class="antes-label">Antes</span>
        <div class="past-digits">${(first.last_digits || [])
          .slice(-6)
          .map(
            (d) =>
              `<span class="past-chip" style="color:${DIGIT_COLORS[d]};border-color:${DIGIT_COLORS[d]}55">${d}</span>`
          )
          .join("")}</div>
      </div>
      <div class="arrow-pick">→</div>
      <div class="pick-block">
        <span class="pick-label">Proximo</span>
        <div class="mega-digit" id="overviewMegaDigit">${first.expert_digit}</div>
      </div>
    </div>
    <p class="agent-says">${first.agent_says || stripMd((first.verdict_short || "").slice(0, 200))}</p>`;
  styleMegaDigit($("overviewMegaDigit"), first.expert_digit);
}

function q(province) {
  return province ? `?province=${encodeURIComponent(province)}` : "";
}

function tickClock() {
  const now = new Date();
  $("liveClock").textContent = now.toLocaleTimeString("es-AR");
}

function setLastUpdate() {
  $("lastUpdate").textContent = `Actualizado ${new Date().toLocaleTimeString("es-AR")}`;
}

function showView(mode) {
  $("viewOverview").classList.toggle("active", mode === "overview");
  $("viewDetail").classList.toggle("active", mode === "detail");
  $("viewCaja").classList.toggle("active", mode === "caja");
}

function selectProvince(id) {
  currentProvince = id;
  document.querySelectorAll(".province-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.province === id);
  });
  if (id === "overview") {
    clearInterval(countdownTimer);
    showView("overview");
    $("viewTitle").textContent = "Vista general";
    $("viewSubtitle").textContent = "Todas las provincias";
    loadOverview();
  } else if (id === "caja") {
    clearInterval(countdownTimer);
    showView("caja");
    $("viewTitle").textContent = "Caja de apuestas";
    $("viewSubtitle").textContent = "Numeros jugados · gastos · ganancias";
    loadCaja();
  } else {
    showView("detail");
    const name = config.provinces.find((p) => p.id === id)?.name || id;
    $("viewTitle").textContent = name;
    $("viewSubtitle").textContent = "Ultima cifra · 4 sorteos diarios";
    loadDetail(id);
  }
}

function buildNav() {
  const nav = $("provinceNav");
  let html = `<button class="province-btn active" data-province="overview">Todas</button>`;
  html += `<button class="province-btn caja-btn" data-province="caja">Caja</button>`;
  for (const p of config.provinces) {
    html += `<button class="province-btn" data-province="${p.id}">${p.name}</button>`;
  }
  nav.innerHTML = html;
  nav.querySelectorAll(".province-btn").forEach((btn) => {
    btn.addEventListener("click", () => selectProvince(btn.dataset.province));
  });
}

function renderOverview(data) {
  const grid = $("overviewGrid");
  grid.innerHTML = data.provinces
    .map((p) => {
      if (!p.has_data) {
        return `
        <article class="province-card empty" data-province="${p.province}">
          <h3>${p.name}</h3>
          <p class="muted">Sin datos aun</p>
          <button class="btn ghost sm">Ver</button>
        </article>`;
      }
      const nd = p.next_draw;
      const pick = p.expert_digit ?? p.math_digit;
      const antes = (p.last_digits || []).slice(-5);
      const antesHtml = antes.length
        ? antes.map((d) => `<span style="color:${DIGIT_COLORS[d]}">${d}</span>`).join(" → ")
        : "—";
      const when = nd?.next_draw_time ? ` · ${nd.next_draw_time}` : "";
      const countdown = nd?.countdown_label ? `<p class="next-countdown-sm">${nd.countdown_label}</p>` : "";
      return `
      <article class="province-card" data-province="${p.province}">
        <h3>${p.name}</h3>
        <p class="next-line">${nd.next_draw_name || nd.next_draw}${when}</p>
        ${countdown}
        <p class="antes-mini">Antes: ${antesHtml}</p>
        <div class="card-mega-digit" data-digit="${pick}" style="color:${DIGIT_COLORS[pick]}">${pick}</div>
        <p class="pick-sublabel jugar-mini">JUGA ESTE</p>
        <button class="btn ghost sm">Ver analisis</button>
      </article>`;
    })
    .join("");

  grid.querySelectorAll(".province-card").forEach((card) => {
    card.addEventListener("click", () => {
      if (card.dataset.province !== "overview") {
        selectProvince(card.dataset.province);
      }
    });
  });
}

async function loadOverview() {
  const data = await fetchJson("/api/dashboard");
  renderOverviewMega(data.provinces);
  renderOverview(data);
  setLastUpdate();
}

function renderBars(probs, container) {
  container.innerHTML = "";
  const entries = Object.entries(probs).map(([d, p]) => [Number(d), p]);
  const max = Math.max(...entries.map(([, p]) => p), 0.01);
  entries.sort((a, b) => a[0] - b[0]);
  for (const [digit, prob] of entries) {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <span>${digit}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${(prob / max) * 100}%"></div></div>
      <span>${pct(prob)}</span>`;
    container.appendChild(row);
  }
}

function renderRanking(ranking, list) {
  list.innerHTML = ranking
    .map((r, i) => `<li class="${i === 0 ? "top" : ""}">${r.digit} - ${pct(r.prob)}</li>`)
    .join("");
}

function renderRecent(data) {
  const el = $("recentList");
  const next = data.next;
  const pred = data.prediction?.digit;
  let html = data.recent
    .map(
      (r) => `
    <div class="recent-item">
      <span>${r.date} | ${DRAW_NAMES[r.draw_type] || r.draw_type}</span>
      <span>${r.number}</span>
      <span class="digit">${r.last_digit}</span>
    </div>`
    )
    .join("");
  html += `
    <div class="recent-item pending">
      <span>PROXIMO</span>
      <span>${DRAW_NAMES[next.next_draw] || next.next_draw}</span>
      <span class="digit">${pred ?? "?"}</span>
    </div>`;
  el.innerHTML = html;
}

function renderPerDraw(predictions) {
  $("perDraw").innerHTML = Object.entries(predictions)
    .map(
      ([type, p]) => `
    <div class="per-draw-card">
      <div>${DRAW_NAMES[type] || type}</div>
      <div class="big">${p.digit}</div>
      <div>${pct(p.probability)}</div>
    </div>`
    )
    .join("");
}

function renderStats30(stats, fourStats) {
  let html = stats.global_frequency
    .map(
      (s) => `
    <div class="stat-chip">
      <div class="d">${s.digit}</div>
      <div class="pct">${s.pct}%</div>
    </div>`
    )
    .join("");

  if (fourStats?.by_draw) {
    html += `<div class="stats-by-draw">`;
    for (const [type, rows] of Object.entries(fourStats.by_draw)) {
      const hot = [...rows].sort((a, b) => b.count - a.count)[0];
      html += `<p class="rank-mini"><strong>${DRAW_NAMES[type] || type}:</strong> mas salio ${hot.digit} (${hot.count}x)</p>`;
    }
    html += `</div>`;
  }
  $("stats30").innerHTML = html;
}

function renderMartingale(plan) {
  $("martingaleTable").innerHTML = `
    <thead><tr><th>#</th><th>Apuesta</th><th>Total</th><th>Ganancia</th></tr></thead>
    <tbody>${plan.steps
      .map(
        (s) =>
          `<tr><td>${s.attempt}</td><td>$${s.bet}</td><td>$${s.cumulative_staked}</td><td>$${s.profit_if_win_now}</td></tr>`
      )
      .join("")}</tbody>`;
}

async function loadMartingale() {
  const base = Number($("baseBet").value) || 100;
  const max = Number($("maxAttempts").value) || 4;
  const plan = await fetchJson(`/api/martingale?base_bet=${base}&max_attempts=${max}`);
  renderMartingale(plan);
}

function stripMd(s) {
  return (s || "").replace(/\*\*/g, "");
}

function renderVerifyDay(daySnap) {
  const grid = $("verifyDay");
  const note = $("verifyNote");
  if (!grid || !daySnap?.draws?.length) {
    if (grid) grid.innerHTML = "<p class='muted'>Sin datos del ultimo dia</p>";
    return;
  }
  note.textContent = daySnap.note || "";
  grid.innerHTML = daySnap.draws
    .map(
      (d) => `
    <div class="verify-item">
      <span>${d.draw_name}</span>
      <span class="num4">${d.number}</span>
      <span class="term" style="color:${DIGIT_COLORS[d.last_digit]}">→ ${d.last_digit}</span>
    </div>`
    )
    .join("");
}

function renderCrossDraw(cross) {
  if (!cross) return;
  const c = cross.consensus;
  $("crossAgent").textContent = c?.agent_says || cross.global_combined?.agent_says || "";
  styleMegaDigit($("crossDigit"), c?.digit);
  $("crossProb").innerHTML =
    `Confianza cruzada: <strong>${pct(c?.confidence || 0)}</strong> · ` +
    `Global 30d: <strong>${pct(cross.global_combined?.probability || 0)}</strong> (digito ${cross.global_combined?.best_digit})`;

  const probs = {};
  (cross.global_combined?.ranking || []).forEach((r) => {
    probs[r.digit] = r.prob;
  });
  renderBars(probs, $("crossBars"));

  $("crossCompare").innerHTML = (cross.comparison || [])
    .map(
      (row) => `
    <div class="cross-compare-card">
      <strong>${row.draw_name}</strong>
      <div class="row"><span>Prediccion</span><strong style="color:${DIGIT_COLORS[row.predicted]}">${row.predicted}</strong></div>
      <div class="row"><span>Prob 30d</span><strong>${pct(row.math_prob)}</strong></div>
      <div class="row"><span>Mas salio</span><strong>${row.hot_digit} (${row.hot_pct}%)</strong></div>
      <div class="row"><span>vs azar</span><strong>${row.vs_uniform > 0 ? "+" : ""}${row.vs_uniform}%</strong></div>
    </div>`
    )
    .join("");

  const today = cross.today_chain || {};
  let todayHtml = "";
  if (today.completed?.length) {
    todayHtml = `<strong>Hoy ${today.date}:</strong> ` +
      today.completed.map((x) => `${x.draw_name} → ${x.last_digit}`).join(" · ");
    if (today.transition_suggestion != null) {
      todayHtml += `<br/>Transicion al proximo: sugiere <strong style="color:${DIGIT_COLORS[today.transition_suggestion]}">${today.transition_suggestion}</strong> (${pct(today.transition_prob)})`;
    }
  } else {
    todayHtml = "Aun no hay sorteos completados hoy. El consenso aplica a las 4 quinielas del dia.";
  }
  const wd = cross.within_day || {};
  todayHtml += `<br/><span class="muted">Promedio ${wd.avg_unique_digits} terminaciones distintas por dia · ${wd.same_digit_all_four_pct}% dias con misma cifra en las 4.</span>`;
  $("crossToday").innerHTML = todayHtml;
}

function renderFourDraws(daily) {
  if (!daily?.draws?.length) return;
  $("fourDayDate").textContent =
    `Fecha objetivo: ${daily.target_date} · Completados hoy: ${(daily.completed_today || []).length}/4`;

  $("fourDrawsGrid").innerHTML = daily.draws
    .map((slot) => {
      const pick = slot.expert?.pick ?? slot.math?.digit;
      const color = DIGIT_COLORS[pick] || "#3dd68c";
      const statusLabel =
        slot.status === "done"
          ? "Ya salio"
          : slot.status === "next"
            ? "Proximo"
            : "Pendiente";
      const rank = (slot.math?.ranking || [])
        .slice(0, 3)
        .map((r) => `${r.digit}(${pct(r.prob)})`)
        .join(" · ");
      let extra = "";
      if (slot.status === "done" && slot.today_result) {
        extra = `<div class="result-done">Salio: ${slot.today_result.number} → ${slot.today_result.last_digit}</div>`;
      } else if (slot.yesterday) {
        extra = `<div class="yesterday-line">Ayer: ${slot.yesterday.number} → ${slot.yesterday.last_digit}</div>`;
      }
      return `
      <article class="four-draw-card ${slot.status}">
        <div class="slot-name">${slot.draw_name}</div>
        <div class="slot-hour">${slot.time || drawTimeLabel(slot.draw_type, slot.hour, slot.minute)}</div>
        <span class="slot-status ${slot.status}">${statusLabel}</span>
        <div class="jugar-mini-title">JUGA ESTE</div>
        <div class="pick-big" style="color:${color}">${pick}</div>
        <div class="prob-line">Stats 30d: <strong>${pct(slot.math?.probability || 0)}</strong> · IA 5d: <strong>${pct(slot.ai?.confidence || 0)}</strong></div>
        <div class="prob-line">Modelo: ${slot.expert?.precision_winner || "-"} (${slot.expert?.precision_pct || 0}%)</div>
        ${extra}
        <div class="rank-mini">Top 3: ${rank || "-"}</div>
      </article>`;
    })
    .join("");
}

function renderExpert(expert, dailyFour) {
  if (!expert) return;
  styleMegaDigit($("expertDigit"), expert.my_pick);
  renderPastDigits($("pastDigits"), expert.sequences?.last_digits);

  if ($("antesLabel")) {
    $("antesLabel").textContent =
      `Ultimas ${expert.draw_type_label || "La Primera"} (solo premio #1)`;
  }
  if ($("sequenceScope")) {
    $("sequenceScope").textContent = expert.sequence_scope || "";
  }

  if ($("playMessage")) {
    $("playMessage").textContent = expert.play_message || "JUGA ESTE";
  }
  if ($("playCallout")) {
    $("playCallout").textContent =
      expert.play_callout || `TERMINACION ${expert.my_pick}`;
  }
  if ($("agentSays")) {
    $("agentSays").textContent = expert.agent_says || stripMd(expert.verdict_summary || "");
  }

  const cmp = expert.precision_comparison;
  $("precisionVerdict").textContent = stripMd(cmp?.verdict || "");
  $("precisionTable").innerHTML = (cmp?.models || [])
    .map((m) => {
      const win = cmp.winner?.mode === m.mode;
      return `
      <div class="precision-row ${win ? "winner" : ""}">
        <span>${m.label}</span>
        <span>${m.hits}/${m.tests} aciertos</span>
        <span class="rate">${m.hit_rate_pct}%</span>
      </div>`;
    })
    .join("");

  $("expertReasons").innerHTML = (expert.reasons || [])
    .map((line) => `<li>${stripMd(line)}</li>`)
    .join("");
  $("expertDisclaimer").textContent = expert.disclaimer || "";

  if (dailyFour) {
    renderFourDraws(dailyFour);
    renderCrossDraw(dailyFour.cross_draw);
    renderVerifyDay(dailyFour.latest_day || expert.latest_day);
  }

  const seq = expert.sequences || {};
  $("sequenceText").textContent = seq.sequence_text || "-";
  $("sequenceList").innerHTML = (seq.sequence || [])
    .slice()
    .reverse()
    .map(
      (s) => `
    <div class="seq-item">
      <span>${s.date}</span>
      <span>${s.number}</span>
      <span class="d">${s.digit}</span>
    </div>`
    )
    .join("");
}

async function loadDetail(province) {
  const qs = q(province);
  const [monitor, analysis, ai] = await Promise.all([
    fetchJson(`/api/recent-results${qs}`),
    fetchJson(`/api/analysis${qs}`),
    fetchJson(`/api/ai${qs}`),
  ]);

  const next = monitor.next;
  const expert = analysis.expert || monitor.expert;
  const nextInfo = analysis.next_draw_info || next;
  renderNextDrawHeader(nextInfo);
  try {
    const ds = await fetchJson("/api/draw-sync");
    drawSyncStatus = ds.status || [];
    renderDrawSchedule(nextInfo);
  } catch {
    /* ignore */
  }

  renderExpert(expert, analysis.daily_four);

  const math = analysis.math_prediction;
  $("mainDigit").textContent = math.digit;
  $("mainProb").textContent = `(${pct(math.probability)})`;

  const aiData = ai.analysis || ai;
  $("aiDigit").textContent = aiData.recommended_digit;
  $("aiConf").textContent = `(${pct(aiData.confidence)})`;

  renderBars(math.probabilities, $("mathBars"));
  renderRanking(math.ranking, $("mathRanking"));
  renderRecent(monitor);
  renderPerDraw(analysis.predictions_by_draw);

  $("aiReasoning").innerHTML = (aiData.reasoning || [])
    .map((line) => `<li>${line}</li>`)
    .join("");
  $("aiContext").textContent = aiData.context_summary || "";

  renderStats30(analysis.stats_30d, analysis.daily_four?.stats_30d_four_draws);
  await loadMartingale();
  setLastUpdate();
}

async function loadStatus() {
  try {
    const st = await fetchJson("/api/status");
    const parts = Object.entries(st.all_provinces || {})
      .map(([k, v]) => `${k.slice(0, 3)}:${v.days}d`)
      .join(" ");
    $("syncStatus").textContent = parts || "OK";
  } catch {
    $("syncStatus").textContent = "Sin conexion";
  }
}

async function syncAll() {
  if (syncing) return;
  syncing = true;
  $("btnSync").disabled = true;
  $("syncStatus").textContent = "Sincronizando...";
  try {
    await fetchJson("/api/sync?days=30&province=all", { method: "POST" });
    await refreshCurrent();
    await loadStatus();
  } catch (e) {
    console.error(e);
    $("syncStatus").textContent = "Error sync";
  } finally {
    $("btnSync").disabled = false;
    syncing = false;
  }
}

async function refreshCurrent() {
  if (currentProvince === "overview" || !currentProvince) {
    await loadOverview();
  } else if (currentProvince === "caja") {
    await loadCaja();
  } else {
    await loadDetail(currentProvince);
  }
}

function drawResultsHash(status) {
  return (status || [])
    .map((s) => `${s.draw_type}:${s.has_result}:${s.result_digit}`)
    .join("|");
}

function renderDrawResultsBar() {
  const bar = $("drawResultsBar");
  if (!bar) return;
  if (!drawSyncStatus.length) {
    bar.innerHTML = "";
    return;
  }
  bar.innerHTML = drawSyncStatus
    .map((s) => {
      if (s.has_result && s.result_digit != null) {
        const c = DIGIT_COLORS[s.result_digit] || "#3dd68c";
        return `<span class="dr-chip done">${s.draw_name} <strong style="color:${c}">${s.result_digit}</strong></span>`;
      }
      if (s.phase === "syncing") {
        return `<span class="dr-chip syncing">${s.draw_name} · actualizando...</span>`;
      }
      if (s.phase === "waiting_sync") {
        return `<span class="dr-chip wait">${s.draw_name} · sync ${s.sync_at}</span>`;
      }
      return `<span class="dr-chip pending">${s.draw_name} ${s.time}</span>`;
    })
    .join("");
}

function updateSyncBadgeFromDraws() {
  const done = drawSyncStatus.filter((s) => s.has_result);
  const last = done[done.length - 1];
  if (last && $("syncStatus")) {
    $("syncStatus").textContent = `Ultimo: ${last.draw_name} → ${last.result_digit}`;
    $("syncStatus").classList.add("updated");
  }
}

async function fetchDrawSyncStatus(triggerCheck = false) {
  if (triggerCheck) {
    const res = await fetchJson("/api/draw-sync/check", { method: "POST" });
    drawSyncStatus = res.status || [];
    return res;
  }
  const res = await fetchJson("/api/draw-sync");
  drawSyncStatus = res.status || [];
  return res;
}

async function applyDrawSyncUI(forceRefresh = false) {
  renderDrawResultsBar();
  const hash = drawResultsHash(drawSyncStatus);
  const changed = hash !== lastDrawResultsHash;
  if (changed) lastDrawResultsHash = hash;
  if (changed || forceRefresh) {
    updateSyncBadgeFromDraws();
    if (currentNextDraw) renderDrawSchedule(currentNextDraw);
    // Siempre refrescar caja cuando hay sorteo nuevo
    if (changed && (currentProvince === "caja" || $("viewCaja")?.classList.contains("active"))) {
      await loadCaja();
    } else {
      await refreshCurrent();
    }
  }
}

async function pollDrawSync() {
  if (!$("autoRefresh")?.checked) return;
  try {
    await fetchDrawSyncStatus(false);
    const needsCheck = drawSyncStatus.some(
      (s) => s.phase === "syncing" || s.phase === "waiting_sync"
    );
    if (needsCheck) {
      const check = await fetchDrawSyncStatus(true);
      if (check.synced?.length) {
        $("syncStatus").textContent = `Actualizado: ${check.synced.map((id) => DRAW_LABEL[id] || id).join(", ")}`;
      }
    }
    await applyDrawSyncUI(false);
    if (currentProvince === "caja") {
      await loadCaja();
    }
  } catch (e) {
    console.error(e);
  }
}

function startTimers() {
  clearInterval(pollTimer);
  clearInterval(syncTimer);
  clearInterval(drawSyncTimer);
  const sec = config.poll_seconds || 30;
  if ($("autoRefresh").checked) {
    pollTimer = setInterval(refreshCurrent, sec * 1000);
    drawSyncTimer = setInterval(pollDrawSync, Math.min(30, sec) * 1000);
    syncTimer = setInterval(syncAll, (config.auto_sync_minutes || 15) * 60 * 1000);
  }
}

async function bootApp(preloadedConfig = null) {
  tickClock();
  setInterval(tickClock, 1000);
  config = preloadedConfig || (await fetchJson("/api/config"));
  buildNav();
  currentProvince = "overview";
  await loadStatus();
  await loadOverview();
  startTimers();
  await fetchDrawSyncStatus(true);
  lastDrawResultsHash = drawResultsHash(drawSyncStatus);
  renderDrawResultsBar();
  updateSyncBadgeFromDraws();
}

async function init() {
  setupLogin();
  const saved = sessionStorage.getItem(APP_KEY);
  try {
    if (saved) {
      const cfg = await fetchJson("/api/config");
      hideLogin();
      await bootApp(cfg);
      return;
    }
    const probe = await fetch(`${API}/api/config`);
    const cfg = await probe.json();
    if (cfg.auth_required && Object.keys(cfg).length === 1) {
      showLogin();
      return;
    }
    hideLogin();
    await bootApp(cfg);
  } catch (e) {
    console.error(e);
    showLogin();
    if ($("syncStatus")) $("syncStatus").textContent = "Error al iniciar";
  }
}

$("btnSync").addEventListener("click", syncAll);
$("autoRefresh").addEventListener("change", startTimers);
$("toggleContext").addEventListener("click", () => {
  $("aiContext").classList.toggle("collapsed");
});
$("baseBet").addEventListener("change", loadMartingale);
$("maxAttempts").addEventListener("change", loadMartingale);
$("btnSaveCajaSettings")?.addEventListener("click", saveCajaSettings);
$("btnProcessCaja")?.addEventListener("click", processCaja);
$("toggleCajaSettings")?.addEventListener("click", () => {
  $("cajaSettingsBody")?.classList.toggle("hidden");
});

init().catch((e) => {
  console.error(e);
  $("syncStatus").textContent = "Error al iniciar";
});
