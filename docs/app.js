const DATA_URL = "data.json";
const AUTO_REFRESH_MS = 60_000;

// Casas con licencia DGOJ vigente en España, verificado a mano el 2026-09-16
// contra el buscador oficial (ordenacionjuego.es/operadores-juego/operadores-
// licencia/operadores, las 78 fichas de operadores, una por una). Claves en
// minúscula, deben coincidir con el `bookmaker` que pone cada provider en
// engine/models.Outcome (ver providers/*.py). Cualquier casa que no esté en
// este set se pinta en rojo en la tabla: o es un fallo de scraping (nombre
// mal parseado) o una casa nueva todavía sin verificar contra la DGOJ — en
// ambos casos, no fiarse de esa fila para dinero real sin comprobarlo. Esta
// verificación es una foto de un momento dado (la DGOJ actualiza el registro
// mensualmente); si ha pasado mucho tiempo, puede estar desfasada.
const DGOJ_LICENSED_BOOKMAKERS = new Set([
  "sportium", "betfair", "winamax", "kirolbet",
  "1xbet", "888sport", "bet365", "betway", "bwin", "codere", "luckia",
  "paf", "retabet", "speedybet", "versus", "williamhill",
  // Vía la plataforma Altenar (providers/altenar.py). Jokerbet: VERAMATIC
  // ONLINE, S.A., comprobado en ordenacionjuego.es el 2026-09-20. Pastón:
  // EUROAPUESTAS ONLINE, comprobado el 2026-09-16.
  "jokerbet", "paston",
  // Betinia (IBERIX GAMING, S.A.U.) y DAZN Bet (DZBT DEPORTES, S.A.): también
  // Altenar; comprobadas en el registro de ordenacionjuego.es el 2026-09-21.
  "betinia", "daznbet",
  // Vía la plataforma Kambi (providers/kambi.py). LeoVegas: LEOESP, S.A. /
  // Leovegas Gaming PLC, comprobado en ordenacionjuego.es el 2026-09-20.
  "leovegas",
  // Yosports (RANK DIGITAL CEUTA, S.A.) y Botemanía (GAMESYS SPAIN, S.A.):
  // también Kambi; comprobadas en el registro de la DGOJ el 2026-09-21.
  "yosports", "botemania",
  // Bet777 (DIGITAL DISTRIBUTION MANAGEMENT IBÉRICA, S.A.), plataforma propia
  // Sportify (providers/bet777.py); registro de la DGOJ, 2026-09-21.
  "bet777",
]);

function isLicensed(bookmaker) {
  return DGOJ_LICENSED_BOOKMAKERS.has(bookmaker.trim().toLowerCase());
}

// URLs oficiales de cada casa, para el panel de acceso rápido.
const BOOKMAKER_URLS = {
  sportium: "https://www.sportium.es",
  betfair: "https://www.betfair.es",
  winamax: "https://www.winamax.es",
  kirolbet: "https://www.kirolbet.es",
  "1xbet": "https://1xbet.es",
  "888sport": "https://www.888sport.es",
  bet365: "https://www.bet365.es",
  betway: "https://www.betway.es",
  bwin: "https://www.bwin.es",
  codere: "https://www.codere.es",
  luckia: "https://www.luckia.es",
  paf: "https://www.paf.es",
  retabet: "https://www.retabet.es",
  speedybet: "https://www.speedybet.es",
  versus: "https://www.versus.es",
  williamhill: "https://www.williamhill.es",
  jokerbet: "https://www.jokerbet.es",
  paston: "https://www.paston.es",
  leovegas: "https://www.leovegas.es",
  betinia: "https://www.betinia.es",
  daznbet: "https://daznbet.es",
  yosports: "https://www.yosports.es",
  botemania: "https://www.botemania.es",
  bet777: "https://www.bet777.es",
};

const PLACED_BETS_KEY = "surebets_placed_bets_v1";
const FILTERS_KEY = "surebets_active_filters_v1";

// Mismos textos que engine/quality.py (FLAG_DESCRIPTIONS).
const FLAG_DESCRIPTIONS = {
  una_sola_casa: "todas las patas son de la misma casa (error de datos)",
  mercado_incompleto: "faltan resultados del mercado (error de datos)",
  lectura_duplicada: "cuotas idénticas a las de otro mercado del mismo partido (tabla del comparador leída dos veces)",
  margen_absurdo: "margen por encima del máximo creíble (error de datos)",
  margen_alto: "margen inusualmente alto: comprueba las cuotas en las casas",
  margen_a_verificar: "margen muy alto: pendiente de verificar (comprueba las cuotas en las casas)",
  margen_verificado: "margen muy alto confirmado con una segunda lectura directa de las casas",
  solo_comparador: "todas las cuotas vienen de comparadores (pueden ir desfasadas)",
  cerca_inicio: "empieza pronto y alguna cuota viene de un comparador",
  cuotas_desfasadas: "las cuotas se leyeron con mucha diferencia de tiempo",
};
const BLOCKING_FLAGS = new Set(["una_sola_casa", "mercado_incompleto", "margen_absurdo", "lectura_duplicada"]);
const RELIABILITY_RANK = { alta: 3, media: 2, baja: 1 };

function loadActiveFilters() {
  try {
    return JSON.parse(localStorage.getItem(FILTERS_KEY)) || {};
  } catch {
    return {};
  }
}

function saveActiveFilters(filters) {
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify(filters));
  } catch {
    /* almacenamiento no disponible: los filtros solo duran esta sesión */
  }
}

function loadPlacedBets() {
  try {
    return JSON.parse(localStorage.getItem(PLACED_BETS_KEY)) || [];
  } catch {
    return [];
  }
}

function savePlacedBets(bets) {
  localStorage.setItem(PLACED_BETS_KEY, JSON.stringify(bets));
}

function marketId(m) {
  return `${m.event}||${m.sport}||${m.market_type}||${m.bookmakers}`;
}

// Reparto que iguala el pago en cualquier resultado: cada importe es
// proporcional a la probabilidad implícita (1/cuota) de su resultado.
// El beneficio garantizado es el pago constante menos lo invertido.
function computeStakeBreakdown(odds, totalStake, step = 0) {
  const totalProb = odds.reduce((s, o) => s + 1 / o.odds, 0);
  const exact = odds.map((o) => (totalStake * (1 / o.odds)) / totalProb);
  const build = (amounts, profit) => ({
    stakes: odds.map((o, i) => ({
      name: o.name,
      bookmaker: o.bookmaker,
      odds: o.odds,
      stake: amounts[i],
      cash_out: o.cash_out ?? null,
      odds_changed_at: o.odds_changed_at ?? null,
    })),
    profit,
    totalProb,
    total: Math.round(amounts.reduce((a, b) => a + b, 0) * 100) / 100,
  });
  if (step > 0 && totalProb < 1) {
    // Importes "naturales" (múltiplos de `step`): a las casas les cuesta más
    // marcar como bot a quien apuesta 240 € en vez de 237,76 €. Se prueba el
    // múltiplo inferior y superior de cada pata y se queda la combinación de
    // mayor rentabilidad que sigue garantizando beneficio en cualquier resultado
    // (misma lógica que engine/arbitrage.py::round_stakes).
    for (const s of step > 1 ? [step, 1] : [step]) {
      const options = exact.map((x) => [
        ...new Set([Math.max(s, Math.floor(x / s) * s), Math.max(s, Math.ceil(x / s) * s)]),
      ]);
      let best = null;
      const walk = (i, acc) => {
        if (i === options.length) {
          const total = acc.reduce((a, b) => a + b, 0);
          const payout = Math.min(...acc.map((a, k) => a * odds[k].odds));
          const profit = payout - total;
          if (profit <= 0) return;
          const roi = profit / total;
          if (!best || roi > best.roi || (roi === best.roi && total < best.total)) best = { acc, roi, total, profit };
          return;
        }
        options[i].forEach((v) => walk(i + 1, [...acc, v]));
      };
      walk(0, []);
      if (best) return build(best.acc, Math.round(best.profit * 100) / 100);
    }
  }
  const amounts = exact.map((x) => Math.round(x * 100) / 100);
  return build(amounts, Math.round((totalStake / totalProb - totalStake) * 100) / 100);
}

// Máximos por apuesta que el usuario anota en limites.json (las APIs públicas de
// las casas no los exponen: dependen de la cuenta). Entre las entradas que casan
// con casa/deporte/mercado gana la más específica y, a igualdad, la más baja.
function findLimit(bookmaker, sport, marketType) {
  let best = null;
  for (const l of state.limits) {
    if (l.casa !== bookmaker.trim().toLowerCase() || !(l.max_stake > 0)) continue;
    if (l.deporte && l.deporte !== sport) continue;
    if (l.mercado && !marketType.startsWith(l.mercado)) continue;
    const specificity = (l.deporte ? 1 : 0) + (l.mercado ? 1 : 0);
    if (!best || specificity > best.specificity || (specificity === best.specificity && l.max_stake < best.max_stake)) {
      best = { max_stake: l.max_stake, specificity, nota: l.nota || "" };
    }
  }
  return best;
}

// Igual que computeStakeBreakdown, pero si alguna pata supera el máximo de su
// casa reduce el TOTAL invertido (todas las patas a la vez, para mantener el
// mismo margen) hasta que todas caben. Con redondeo, subir al múltiplo superior
// puede volver a pasarse por poco, así que se repite reduciendo.
function computeWithLimits(market, totalStake, step) {
  const limitOf = (s) => findLimit(s.bookmaker, market.sport, market.market_type);
  let total = totalStake;
  let result = computeStakeBreakdown(market.odds, total, step);
  for (let i = 0; i < 40; i++) {
    const over = result.stakes.filter((s) => {
      const l = limitOf(s);
      return l && s.stake > l.max_stake;
    });
    if (!over.length) break;
    const factor = Math.min(...over.map((s) => limitOf(s).max_stake / s.stake));
    total = Math.floor(total * Math.min(factor, 0.999) * 100) / 100;
    if (total <= 0) break;
    result = computeStakeBreakdown(market.odds, total, step);
  }
  const stakes = result.stakes.map((s) => ({ ...s, limit: limitOf(s)?.max_stake ?? null }));
  const exceeded = stakes.some((s) => s.limit !== null && s.stake > s.limit);
  return {
    ...result,
    stakes,
    requestedTotal: totalStake,
    capped: result.total < totalStake - 0.005,
    exceeded,
    unknownLimits: [...new Set(stakes.filter((s) => s.limit === null).map((s) => s.bookmaker))],
  };
}

function stakeNotes(s) {
  const notes = [];
  if (s.cash_out === true) notes.push(`<span class="stake-note ok" title="Kambi indica que esta selección admite cash out: hay salida de emergencia (con pérdida del margen) si la otra pata falla">cash out ✓</span>`);
  else if (s.cash_out === false) notes.push(`<span class="stake-note warn" title="Sin cash out en esta selección: si la otra pata falla no hay salida">sin cash out</span>`);
  if (s.odds_changed_at) {
    const mins = (Date.now() - new Date(s.odds_changed_at).getTime()) / 60000;
    // Una cuota que se movió hace poco está viva; una que no se mueve hace horas
    // es normal en mercados nicho, pero el aviso ayuda a comprobarla antes de apostar.
    notes.push(`<span class="stake-note${mins < 3 ? " warn" : ""}" title="Última vez que la casa movió esta cuota${mins < 3 ? " (muy reciente: puede seguir moviéndose)" : ""}">cuota movida ${timeAgo(s.odds_changed_at)}</span>`);
  }
  if (s.limit !== null && s.limit !== undefined) notes.push(`<span class="stake-note" title="Máximo anotado en limites.json">máx. ${money(s.limit)}</span>`);
  return notes.length ? `<div class="stake-notes">${notes.join("")}</div>` : "";
}

function isBlocked(m) {
  return (m.flags || []).some((f) => BLOCKING_FLAGS.has(f));
}

function bookmakerSpan(name) {
  const licensed = isLicensed(name);
  const cls = licensed ? "bookmaker-licensed" : "bookmaker-unlicensed";
  const title = licensed ? "Con licencia DGOJ (verificado 2026-09-16)" : "Sin verificar contra la DGOJ";
  return `<span class="${cls}" title="${title}">${name}${licensed ? "" : " ⚠"}</span>`;
}

let state = {
  comparisons: [],
  sortKey: "margin",
  sortDir: "desc",
  expandedGroups: new Set(),
  placedBets: loadPlacedBets(),
  marketsById: new Map(),
  limits: [],
  activeStakeMarket: null,
  savedSport: "",
  roundStep: "5",
};

try {
  const savedStep = localStorage.getItem("surebets_round_step_v1");
  if (savedStep !== null) state.roundStep = savedStep;
} catch {
  /* sin almacenamiento */
}

function pct(n) {
  return `${(n * 100).toFixed(2)}%`;
}

function money(n) {
  if (n === null || n === undefined) return "—";
  return `${n.toFixed(2)}€`;
}

function timeAgo(iso) {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "hace instantes";
  if (mins < 60) return `hace ${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} d`;
}

function hoursUntil(iso) {
  if (!iso) return null;
  return (new Date(iso).getTime() - Date.now()) / 3600000;
}

function kickoffCell(iso) {
  if (!iso) return '<span class="muted" title="Ninguna fuente directa informa de la hora de inicio">—</span>';
  const h = hoursUntil(iso);
  const date = new Date(iso);
  const text = date.toLocaleString("es-ES", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  let when;
  if (h <= 0) when = "ya empezado";
  else if (h < 1) when = `en ${Math.max(1, Math.round(h * 60))} min`;
  else when = `en ${h.toFixed(1)} h`;
  return `<span class="${h > 0 && h < 3 ? "kickoff-soon" : ""}" title="${text}">${text}<br><small class="muted">${when}</small></span>`;
}

function reliabilityBadge(m) {
  if (!m.reliability) return "—";
  const flags = (m.flags || []).map((f) => FLAG_DESCRIPTIONS[f] || f);
  const title = flags.length ? flags.join(" · ") : "Todas las cuotas vienen directas de la casa";
  const blocked = (m.flags || []).some((f) => BLOCKING_FLAGS.has(f));
  const list = flags.length
    ? `<span class="flag-list ${blocked ? "blocked" : ""}">${flags.map((t) => `⚠ ${t}`).join("<br>")}</span>`
    : "";
  let verification = "";
  if (m.verification === "verificada") {
    verification = ' <span class="pill pill-alta" title="Una segunda lectura directa de las casas, en el mismo escaneo, confirmó este margen tan alto">✓ verificada</span>';
  } else if (m.verification === "pendiente") {
    verification =
      ' <span class="pill pill-media" title="Margen muy alto que no se pudo comprobar en directo (alguna cuota viene de un comparador): solo se avisa tras varios escaneos seguidos. Comprueba las cuotas en las casas.">🔎 en verificación</span>';
  }
  return `<span class="pill pill-${m.reliability}" title="${title}">${m.reliability}</span>${verification}${list}`;
}

function oddsSummary(odds) {
  return odds.map((o) => `${o.name}: ${bookmakerSpan(o.bookmaker)} @${o.odds.toFixed(2)}`).join(" · ");
}

function bookmakersCell(bookmakersStr) {
  return bookmakersStr
    .split(",")
    .map((b) => bookmakerSpan(b))
    .join(", ");
}

function groupMatches(tableId, rows) {
  const map = new Map();
  for (const row of rows) {
    const key = `${tableId}::${row.event}||${row.sport}`;
    if (!map.has(key)) {
      map.set(key, { key, event: row.event, sport: row.sport, markets: [] });
    }
    map.get(key).markets.push(row);
  }
  return [...map.values()].map((g) => {
    const bookmakerSet = new Set();
    let bestMargin = -Infinity;
    let anySurebet = false;
    let lastSeenAt = null;
    let totalProfit = 0;
    let startTime = null;
    let surebetSince = null;
    let blockedCount = 0;
    for (const m of g.markets) {
      m.bookmakers.split(",").forEach((b) => bookmakerSet.add(b.trim()));
      if (!lastSeenAt || new Date(m.last_seen_at) > new Date(lastSeenAt)) lastSeenAt = m.last_seen_at;
      // Los mercados descartados por error de datos (margen absurdo, mercado
      // incompleto...) no cuentan para el mejor margen ni el inicio del partido.
      if (isBlocked(m)) {
        blockedCount++;
        continue;
      }
      if (m.start_time && (!startTime || m.start_time < startTime)) startTime = m.start_time;
      if (m.surebet_since && (!surebetSince || m.surebet_since < surebetSince)) surebetSince = m.surebet_since;
      if (m.margin > bestMargin) bestMargin = m.margin;
      if (m.is_surebet) anySurebet = true;
      if (m.guaranteed_profit) totalProfit += m.guaranteed_profit;
    }
    // Válidos primero (por margen descendente); los descartados, al final.
    g.markets.sort((a, b) => isBlocked(a) - isBlocked(b) || b.margin - a.margin);
    const allBlocked = blockedCount === g.markets.length;
    if (allBlocked) bestMargin = -Infinity;
    return {
      ...g,
      bookmakers: [...bookmakerSet],
      bestMargin,
      anySurebet,
      lastSeenAt,
      totalProfit,
      startTime,
      surebetSince,
      allBlocked,
    };
  });
}

function marginClass(row) {
  if (isBlocked(row)) return "margin-negative";
  if (row.is_surebet) return "margin-positive";
  if (row.margin > 0) return "margin-amber";
  return "margin-negative";
}

function rowClass(row) {
  if (isBlocked(row)) return "row-neutral";
  if (row.is_surebet) return "row-surebet";
  if (row.margin > 0) return "row-amber";
  return "row-neutral";
}

function renderStats(data) {
  const activeSurebets = data.comparisons.filter((c) => c.is_surebet);
  const valid = data.comparisons.filter((c) => !(c.flags || []).some((f) => BLOCKING_FLAGS.has(f)));
  const bestValid = valid.length ? Math.max(...valid.map((c) => c.margin)) : null;
  const realProfit = state.placedBets.reduce((s, b) => s + (b.profit || 0), 0);
  const realInvested = state.placedBets.reduce((s, b) => s + (b.total_stake || 0), 0);

  const trusted = activeSurebets.filter((c) => (RELIABILITY_RANK[c.reliability] || 0) >= 2);
  const discarded = data.comparisons.filter((c) => (c.flags || []).some((f) => BLOCKING_FLAGS.has(f)));
  const cards = [
    { label: "Surebets activas", value: activeSurebets.length, highlight: activeSurebets.length > 0 },
    { label: "Fiabilidad media o alta", value: trusted.length, highlight: trusted.length > 0 },
    { label: "En verificación (margen muy alto)", value: activeSurebets.filter((c) => c.verification === "pendiente").length },
    { label: "Descartadas (error de datos)", value: discarded.length },
    { label: "Comparaciones activas", value: data.comparisons.length },
    { label: "Mejor margen (válido)", value: bestValid !== null ? pct(bestValid) : "—" },
    { label: `Detectadas (${data.stats.period_days}d)`, value: data.stats.count },
    { label: "Invertido (apuestas colocadas)", value: money(realInvested) },
    { label: "Beneficio real (apuestas colocadas)", value: money(realProfit), highlight: state.placedBets.length > 0 },
  ];

  document.getElementById("stats-grid").innerHTML = cards
    .map(
      (c) => `
      <div class="stat-card ${c.highlight ? "highlight" : ""}">
        <div class="label">${c.label}</div>
        <div class="value">${c.value}</div>
      </div>`
    )
    .join("");
}

function stakeActionButton(m) {
  const id = marketId(m);
  state.marketsById.set(id, m);
  return `<button class="btn-place" data-market-id="${id}">Calcular y marcar</button>`;
}

function ageCell(iso) {
  return iso ? timeAgo(iso).replace("hace ", "") : "—";
}

function activeGroupRowsHtml(g) {
  const single = g.markets.length === 1;
  const expanded = !single && state.expandedGroups.has(g.key);
  const chevron = single ? "•" : expanded ? "▾" : "▸";
  const summary = `
    <tr class="row-surebet group-row" data-group-key="${g.key}">
      <td class="event-cell"><span class="chevron">${chevron}</span> ${g.event}</td>
      <td>${kickoffCell(g.startTime)}</td>
      <td>${g.sport}</td>
      <td>${single ? g.markets[0].market_type : `${g.markets.length} mercados`}</td>
      <td>${g.bookmakers.map(bookmakerSpan).join(", ")}</td>
      <td class="odds-cell">${single ? oddsSummary(g.markets[0].odds) : "Ver detalle ▸"}</td>
      <td class="margin-value margin-positive">${pct(g.bestMargin)}</td>
      <td>${reliabilityBadge(g.markets[0])}</td>
      <td>${single ? stakeActionButton(g.markets[0]) : "—"}</td>
      <td>${ageCell(g.surebetSince)}</td>
    </tr>`;
  if (!expanded || single) return summary;
  const detailRows = g.markets
    .map(
      (m) => `
      <tr class="row-surebet detail-row">
        <td class="event-cell detail-indent">↳</td>
        <td></td>
        <td></td>
        <td>${m.market_type}</td>
        <td>${bookmakersCell(m.bookmakers)}</td>
        <td class="odds-cell">${oddsSummary(m.odds)}</td>
        <td class="margin-value margin-positive">${pct(m.margin)}</td>
        <td>${reliabilityBadge(m)}</td>
        <td>${stakeActionButton(m)}</td>
        <td>${ageCell(m.surebet_since)}</td>
      </tr>`
    )
    .join("");
  return summary + detailRows;
}

function readActiveFilters() {
  const num = (id) => {
    const v = parseFloat(document.getElementById(id).value);
    return Number.isFinite(v) ? v : null;
  };
  return {
    sport: document.getElementById("a-filter-sport").value,
    reliability: document.getElementById("a-filter-reliability").value,
    start: document.getElementById("a-filter-start").value,
    min: num("a-filter-min"),
    max: num("a-filter-max"),
    sort: document.getElementById("a-sort").value,
  };
}

function restoreActiveFilters() {
  const saved = loadActiveFilters();
  const set = (id, v) => {
    if (v !== undefined && v !== null) document.getElementById(id).value = v;
  };
  set("a-filter-reliability", saved.reliability);
  set("a-filter-start", saved.start);
  set("a-filter-min", saved.min);
  set("a-filter-max", saved.max);
  set("a-sort", saved.sort);
  state.savedSport = saved.sport || "";
}

function passesActiveFilters(c, f) {
  if (f.sport && c.sport !== f.sport) return false;
  if (f.reliability !== "any" && (RELIABILITY_RANK[c.reliability] || 0) < RELIABILITY_RANK[f.reliability]) return false;
  if (f.start !== "any") {
    const h = hoursUntil(c.start_time);
    if (h === null || h <= 0 || h > parseFloat(f.start)) return false;
  }
  if (f.min !== null && c.margin * 100 < f.min) return false;
  if (f.max !== null && c.margin * 100 > f.max) return false;
  return true;
}

function sortActiveGroups(groups, sort) {
  const far = Number.MAX_SAFE_INTEGER;
  const byStart = (g) => (g.startTime ? new Date(g.startTime).getTime() : far);
  const byAge = (g) => (g.surebetSince ? new Date(g.surebetSince).getTime() : far);
  if (sort === "start") return groups.sort((a, b) => byStart(a) - byStart(b) || b.bestMargin - a.bestMargin);
  if (sort === "age") return groups.sort((a, b) => byAge(a) - byAge(b) || b.bestMargin - a.bestMargin);
  return groups.sort((a, b) => b.bestMargin - a.bestMargin);
}

function renderActiveTable(data) {
  state.marketsById.clear();
  const allActive = data.comparisons.filter((c) => c.is_surebet);

  const sportSel = document.getElementById("a-filter-sport");
  const sports = [...new Set(allActive.map((c) => c.sport))].sort();
  const current = sportSel.value || state.savedSport || "";
  sportSel.innerHTML =
    '<option value="">Todos los deportes</option>' + sports.map((v) => `<option value="${v}">${v}</option>`).join("");
  if (sports.includes(current)) sportSel.value = current;

  const filters = readActiveFilters();
  saveActiveFilters(filters);
  const active = allActive.filter((c) => passesActiveFilters(c, filters));
  const groups = sortActiveGroups(groupMatches("active", active), filters.sort);

  document.getElementById("active-count").textContent = groups.length;
  const tbody = document.querySelector("#active-table tbody");
  const empty = document.getElementById("active-empty");

  if (!groups.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  tbody.innerHTML = groups.map(activeGroupRowsHtml).join("");
}

function populateFilterOptions(data) {
  const sportSel = document.getElementById("filter-sport");
  const marketSel = document.getElementById("filter-market");
  const sports = [...new Set(data.comparisons.map((c) => c.sport))].sort();
  const markets = [...new Set(data.comparisons.map((c) => c.market_type))].sort();

  const keepValue = (sel, values, label) => {
    const current = sel.value;
    sel.innerHTML =
      `<option value="">${label}</option>` +
      values.map((v) => `<option value="${v}">${v}</option>`).join("");
    if (values.includes(current)) sel.value = current;
  };

  keepValue(sportSel, sports, "Todos los deportes");
  keepValue(marketSel, markets, "Todos los mercados");
}

function applyFilters(comparisons) {
  const search = document.getElementById("filter-search").value.trim().toLowerCase();
  const sport = document.getElementById("filter-sport").value;
  const market = document.getElementById("filter-market").value;
  const surebetOnly = document.getElementById("filter-surebet-only").checked;
  const start = document.getElementById("filter-start").value;

  return comparisons.filter((c) => {
    if (start !== "any") {
      const h = hoursUntil(c.start_time);
      if (h === null || h <= 0 || h > parseFloat(start)) return false;
    }
    if (search && !c.event.toLowerCase().includes(search)) return false;
    if (sport && c.sport !== sport) return false;
    if (market && c.market_type !== market) return false;
    if (surebetOnly && !c.is_surebet) return false;
    return true;
  });
}

function groupStatusPill(g) {
  const top = g.markets[0];
  if (g.allBlocked) {
    const why = top.flags
      .filter((f) => BLOCKING_FLAGS.has(f))
      .map((f) => FLAG_DESCRIPTIONS[f])
      .join(" · ");
    return `<span class="pill pill-baja" title="${why}">Descartada</span>`;
  }
  return g.anySurebet
    ? '<span class="pill pill-surebet">Surebet</span>'
    : '<span class="pill pill-none">Sin arbitraje</span>';
}

function groupMarginClass(g) {
  if (g.allBlocked) return "margin-negative";
  if (g.anySurebet) return "margin-positive";
  if (g.bestMargin > 0) return "margin-amber";
  return "margin-negative";
}

function groupRowClass(g) {
  if (g.allBlocked) return "row-neutral";
  if (g.anySurebet) return "row-surebet";
  if (g.bestMargin > 0) return "row-amber";
  return "row-neutral";
}

function allGroupRowsHtml(g) {
  const single = g.markets.length === 1;
  const expanded = !single && state.expandedGroups.has(g.key);
  const chevron = single ? "•" : expanded ? "▾" : "▸";
  const summary = `
    <tr class="${groupRowClass(g)} group-row" data-group-key="${g.key}">
      <td class="event-cell"><span class="chevron">${chevron}</span> ${g.event}</td>
      <td>${kickoffCell(g.startTime)}</td>
      <td>${g.sport}</td>
      <td>${single ? g.markets[0].market_type : `${g.markets.length} mercados`}</td>
      <td>${g.bookmakers.map(bookmakerSpan).join(", ")}</td>
      <td class="odds-cell">${single ? oddsSummary(g.markets[0].odds) : "Ver detalle ▸"}</td>
      <td class="margin-value ${groupMarginClass(g)}">${g.allBlocked ? "—" : pct(g.bestMargin)}</td>
      <td>${groupStatusPill(g)}</td>
      <td>${timeAgo(g.lastSeenAt)}</td>
    </tr>`;
  if (!expanded || single) return summary;
  const detailRows = g.markets
    .map(
      (m) => `
      <tr class="${rowClass(m)} detail-row">
        <td class="event-cell detail-indent">↳</td>
        <td></td>
        <td></td>
        <td>${m.market_type}</td>
        <td>${bookmakersCell(m.bookmakers)}</td>
        <td class="odds-cell">${oddsSummary(m.odds)}</td>
        <td class="margin-value ${marginClass(m)}">${pct(m.margin)}</td>
        <td>${
          isBlocked(m)
            ? `<span class="pill pill-baja" title="${(m.flags || []).filter((f) => BLOCKING_FLAGS.has(f)).map((f) => FLAG_DESCRIPTIONS[f]).join(" · ")}">Descartada</span>`
            : m.is_surebet
              ? '<span class="pill pill-surebet">Surebet</span>'
              : '<span class="pill pill-none">Sin arbitraje</span>'
        }</td>
        <td>${timeAgo(m.last_seen_at)}</td>
      </tr>`
    )
    .join("");
  return summary + detailRows;
}

function sortGroups(groups) {
  const { sortKey, sortDir } = state;
  const dir = sortDir === "asc" ? 1 : -1;
  const keyed = {
    event: (g) => g.event,
    sport: (g) => g.sport,
    start: (g) => (g.startTime ? new Date(g.startTime).getTime() : Number.MAX_SAFE_INTEGER),
    margin: (g) => g.bestMargin,
    last_seen_at: (g) => new Date(g.lastSeenAt).getTime(),
  };
  const getValue = keyed[sortKey] || keyed.margin;
  return [...groups].sort((a, b) => {
    if (a.allBlocked !== b.allBlocked) return a.allBlocked ? 1 : -1;
    const av = getValue(a);
    const bv = getValue(b);
    if (typeof av === "string") return av.localeCompare(bv) * dir;
    return (av - bv) * dir;
  });
}

function renderAllTable(data) {
  populateFilterOptions(data);
  const filtered = applyFilters(data.comparisons);
  const groups = sortGroups(groupMatches("all", filtered));

  document.getElementById("all-count").textContent = `${groups.length} partidos (${filtered.length} comparaciones) / ${data.comparisons.length} totales`;
  const tbody = document.querySelector("#all-table tbody");
  const empty = document.getElementById("all-empty");

  if (!groups.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  tbody.innerHTML = groups.map(allGroupRowsHtml).join("");
}

function renderHistoryTable(data) {
  const rows = data.recent_opportunities || [];
  document.getElementById("history-count").textContent = rows.length;
  const tbody = document.querySelector("#history-table tbody");
  const empty = document.getElementById("history-empty");

  if (!rows.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  tbody.innerHTML = rows
    .map(
      (row) => `
      <tr>
        <td>${timeAgo(row.detected_at)}</td>
        <td class="event-cell">${row.event}</td>
        <td>${row.sport}</td>
        <td>${row.market_type}</td>
        <td>${bookmakersCell(row.bookmakers)}</td>
        <td class="margin-value margin-positive">${pct(row.margin)}</td>
        <td>${money(row.guaranteed_profit)}</td>
      </tr>`
    )
    .join("");
}

function renderPlacedBets() {
  const bets = [...state.placedBets].sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
  document.getElementById("placed-count").textContent = bets.length;
  const tbody = document.querySelector("#placed-table tbody");
  const empty = document.getElementById("placed-empty");

  if (!bets.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  tbody.innerHTML = bets
    .map(
      (b) => `
      <tr>
        <td>${timeAgo(b.placed_at)}</td>
        <td class="event-cell">${b.event}</td>
        <td>${b.market_type}</td>
        <td class="odds-cell">${b.stakes
          .map((s) => `${s.name}: ${bookmakerSpan(s.bookmaker)} ${money(s.stake)}`)
          .join(" · ")}</td>
        <td>${money(b.total_stake)}</td>
        <td class="margin-value margin-positive">${money(b.profit)}</td>
        <td><button class="btn-delete" data-bet-id="${b.id}" title="Quitar del registro">✕</button></td>
      </tr>`
    )
    .join("");
}

function renderBookmakersPanel() {
  const container = document.getElementById("bookmaker-links");
  if (!container) return;
  const names = [...DGOJ_LICENSED_BOOKMAKERS].sort();
  container.innerHTML = names
    .map((key) => {
      const url = BOOKMAKER_URLS[key];
      const label = key.charAt(0).toUpperCase() + key.slice(1);
      return url
        ? `<a class="bookmaker-link" href="${url}" target="_blank" rel="noopener">${label} ↗</a>`
        : `<span class="bookmaker-link bookmaker-link-disabled">${label}</span>`;
    })
    .join("");
}

function openStakeModal(marketId2) {
  const market = state.marketsById.get(marketId2);
  if (!market) return;
  state.activeStakeMarket = market;
  document.getElementById("stake-modal-title").textContent = `${market.event} — ${market.market_type}`;
  document.getElementById("stake-total-input").value = "";
  document.getElementById("stake-round-select").value = state.roundStep;
  document.querySelector("#stake-breakdown-table tbody").innerHTML = "";
  document.getElementById("stake-summary").innerHTML = "";
  document.getElementById("stake-modal").hidden = false;
  document.getElementById("stake-total-input").focus();
}

function closeStakeModal() {
  document.getElementById("stake-modal").hidden = true;
  state.activeStakeMarket = null;
}

function recalcStakeModal() {
  const market = state.activeStakeMarket;
  if (!market) return;
  const totalStake = parseFloat(document.getElementById("stake-total-input").value);
  const tbody = document.querySelector("#stake-breakdown-table tbody");
  const summary = document.getElementById("stake-summary");
  if (!totalStake || totalStake <= 0) {
    tbody.innerHTML = "";
    summary.innerHTML = "";
    return;
  }
  const step = parseFloat(document.getElementById("stake-round-select").value) || 0;
  const { stakes, profit, total, capped, exceeded, unknownLimits } = computeWithLimits(market, totalStake, step);
  tbody.innerHTML = stakes
    .map(
      (s) => `
      <tr>
        <td>${s.name}</td>
        <td>${bookmakerSpan(s.bookmaker)}${stakeNotes(s)}</td>
        <td>@${s.odds.toFixed(2)}</td>
        <td><strong>${money(s.stake)}</strong></td>
      </tr>`
    )
    .join("");
  const extra = step > 0 && !capped && Math.abs(total - totalStake) >= 0.01 ? ` (invirtiendo ${money(total)} en total)` : "";
  let html = `Beneficio garantizado, gane quien gane: <strong class="margin-positive">${money(profit)}</strong>${extra}`;
  if (capped) {
    html += `<div class="stake-warning">⚠ Límite de casa: el total se reduce de ${money(totalStake)} a ${money(total)} para que ninguna pata pase de su máximo (mismo margen, menos dinero).</div>`;
  }
  if (exceeded) {
    html += `<div class="stake-warning">⚠ Aun así alguna pata supera su máximo anotado: el importe es demasiado pequeño para repartirlo.</div>`;
  }
  if (unknownLimits.length) {
    html += `<div class="stake-hint">Sin máximo anotado para ${unknownLimits.join(", ")}: mide el límite en el boleto (importe enorme, sin confirmar) y anótalo en <code>docs/limites.json</code>. Si una casa acepta menos de lo pedido, recalcula y cubre la diferencia.</div>`;
  }
  summary.innerHTML = html;
}

function confirmStakeModal() {
  const market = state.activeStakeMarket;
  const totalStake = parseFloat(document.getElementById("stake-total-input").value);
  if (!market || !totalStake || totalStake <= 0) return;
  const step = parseFloat(document.getElementById("stake-round-select").value) || 0;
  const { stakes, profit, total } = computeWithLimits(market, totalStake, step);
  state.roundStep = String(step);
  try {
    localStorage.setItem("surebets_round_step_v1", state.roundStep);
  } catch {
    /* sin almacenamiento: solo se recuerda en esta sesión */
  }
  state.placedBets.push({
    id: `${marketId(market)}||${Date.now()}`,
    event: market.event,
    sport: market.sport,
    market_type: market.market_type,
    bookmakers: market.bookmakers,
    total_stake: total,
    stakes,
    profit,
    placed_at: new Date().toISOString(),
  });
  savePlacedBets(state.placedBets);
  closeStakeModal();
  renderPlacedBets();
  if (window.__surebetsData) renderStats(window.__surebetsData);
}

function deletePlacedBet(betId) {
  state.placedBets = state.placedBets.filter((b) => b.id !== betId);
  savePlacedBets(state.placedBets);
  renderPlacedBets();
  if (window.__surebetsData) renderStats(window.__surebetsData);
}

function render(data) {
  state.comparisons = data.comparisons;
  renderStats(data);
  renderActiveTable(data);
  renderPlacedBets();
  renderAllTable(data);
  renderHistoryTable(data);

  const generated = data.generated_at ? new Date(data.generated_at) : null;
  document.getElementById("last-updated").textContent = generated
    ? `Actualizado ${timeAgo(data.generated_at)} (${generated.toLocaleString("es-ES")})`
    : "Sin datos todavía — esperando al primer escaneo";
}

async function loadLimits() {
  try {
    const res = await fetch(`limites.json?t=${Date.now()}`);
    const data = await res.json();
    state.limits = (data.limites || []).map((l) => ({ ...l, casa: String(l.casa || "").trim().toLowerCase() }));
  } catch {
    state.limits = []; // sin fichero o mal formado: el panel funciona igual, sin límites
  }
}

async function load() {
  await loadLimits();
  try {
    const res = await fetch(`${DATA_URL}?t=${Date.now()}`);
    const data = await res.json();
    window.__surebetsData = data;
    render(data);
  } catch (err) {
    document.getElementById("last-updated").textContent = "Error cargando datos";
    console.error(err);
  }
}

function toggleGroupRow(e, rerender) {
  const tr = e.target.closest("tr.group-row");
  if (!tr) return;
  const key = tr.dataset.groupKey;
  if (state.expandedGroups.has(key)) state.expandedGroups.delete(key);
  else state.expandedGroups.add(key);
  if (window.__surebetsData) rerender(window.__surebetsData);
}

function wireControls() {
  document.getElementById("refresh-btn").addEventListener("click", load);
  restoreActiveFilters();
  ["a-filter-sport", "a-filter-reliability", "a-filter-start", "a-filter-min", "a-filter-max", "a-sort"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      if (window.__surebetsData) renderActiveTable(window.__surebetsData);
    });
  });
  document.getElementById("stake-round-select").addEventListener("input", recalcStakeModal);
  ["filter-search", "filter-sport", "filter-market", "filter-start", "filter-surebet-only"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      if (window.__surebetsData) renderAllTable(window.__surebetsData);
    });
  });

  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        // Por inicio, lo natural es ver primero el partido que empieza antes.
        state.sortDir = key === "start" ? "asc" : "desc";
      }
      if (window.__surebetsData) renderAllTable(window.__surebetsData);
    });
  });

  document.querySelector("#active-table tbody").addEventListener("click", (e) => {
    const placeBtn = e.target.closest(".btn-place");
    if (placeBtn) {
      openStakeModal(placeBtn.dataset.marketId);
      return;
    }
    toggleGroupRow(e, renderActiveTable);
  });
  document.querySelector("#all-table tbody").addEventListener("click", (e) => toggleGroupRow(e, renderAllTable));

  document.querySelector("#placed-table tbody").addEventListener("click", (e) => {
    const delBtn = e.target.closest(".btn-delete");
    if (delBtn) deletePlacedBet(delBtn.dataset.betId);
  });

  document.getElementById("stake-total-input").addEventListener("input", recalcStakeModal);
  document.getElementById("stake-modal-close").addEventListener("click", closeStakeModal);
  document.getElementById("stake-cancel-btn").addEventListener("click", closeStakeModal);
  document.getElementById("stake-confirm-btn").addEventListener("click", confirmStakeModal);
  document.getElementById("stake-modal").addEventListener("click", (e) => {
    if (e.target.id === "stake-modal") closeStakeModal();
  });

  renderBookmakersPanel();
}

wireControls();
load();
setInterval(load, AUTO_REFRESH_MS);
