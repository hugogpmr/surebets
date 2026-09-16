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
]);

function isLicensed(bookmaker) {
  return DGOJ_LICENSED_BOOKMAKERS.has(bookmaker.trim().toLowerCase());
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
};

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
    for (const m of g.markets) {
      m.bookmakers.split(",").forEach((b) => bookmakerSet.add(b.trim()));
      if (m.margin > bestMargin) bestMargin = m.margin;
      if (m.is_surebet) anySurebet = true;
      if (m.guaranteed_profit) totalProfit += m.guaranteed_profit;
      if (!lastSeenAt || new Date(m.last_seen_at) > new Date(lastSeenAt)) lastSeenAt = m.last_seen_at;
    }
    g.markets.sort((a, b) => b.margin - a.margin);
    return {
      ...g,
      bookmakers: [...bookmakerSet],
      bestMargin,
      anySurebet,
      lastSeenAt,
      totalProfit,
    };
  });
}

function marginClass(row) {
  if (row.is_surebet) return "margin-positive";
  if (row.margin > 0) return "margin-amber";
  return "margin-negative";
}

function rowClass(row) {
  if (row.is_surebet) return "row-surebet";
  if (row.margin > 0) return "row-amber";
  return "row-neutral";
}

function renderStats(data) {
  const activeSurebets = data.comparisons.filter((c) => c.is_surebet);
  const bestMargin = data.comparisons.length
    ? Math.max(...data.comparisons.map((c) => c.margin))
    : null;

  const cards = [
    { label: "Surebets activas", value: activeSurebets.length, highlight: activeSurebets.length > 0 },
    { label: "Comparaciones activas", value: data.comparisons.length },
    { label: "Mejor margen ahora", value: bestMargin !== null ? pct(bestMargin) : "—" },
    { label: `Detectadas (${data.stats.period_days}d)`, value: data.stats.count },
    { label: `Beneficio potencial (${data.stats.period_days}d)`, value: money(data.stats.total_potential_profit) },
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

function activeGroupRowsHtml(g) {
  const single = g.markets.length === 1;
  const expanded = !single && state.expandedGroups.has(g.key);
  const chevron = single ? "•" : expanded ? "▾" : "▸";
  const summary = `
    <tr class="row-surebet group-row" data-group-key="${g.key}">
      <td class="event-cell"><span class="chevron">${chevron}</span> ${g.event}</td>
      <td>${g.sport}</td>
      <td>${single ? g.markets[0].market_type : `${g.markets.length} mercados`}</td>
      <td>${g.bookmakers.map(bookmakerSpan).join(", ")}</td>
      <td class="odds-cell">${single ? oddsSummary(g.markets[0].odds) : "Ver detalle ▸"}</td>
      <td class="margin-value margin-positive">${pct(g.bestMargin)}</td>
      <td>${money(g.totalProfit)}</td>
      <td>${timeAgo(g.lastSeenAt)}</td>
    </tr>`;
  if (!expanded || single) return summary;
  const detailRows = g.markets
    .map(
      (m) => `
      <tr class="row-surebet detail-row">
        <td class="event-cell detail-indent">↳</td>
        <td></td>
        <td>${m.market_type}</td>
        <td>${bookmakersCell(m.bookmakers)}</td>
        <td class="odds-cell">${oddsSummary(m.odds)}</td>
        <td class="margin-value margin-positive">${pct(m.margin)}</td>
        <td>${money(m.guaranteed_profit)}</td>
        <td>${timeAgo(m.last_seen_at)}</td>
      </tr>`
    )
    .join("");
  return summary + detailRows;
}

function renderActiveTable(data) {
  const active = data.comparisons.filter((c) => c.is_surebet);
  const groups = groupMatches("active", active).sort((a, b) => b.bestMargin - a.bestMargin);

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

  return comparisons.filter((c) => {
    if (search && !c.event.toLowerCase().includes(search)) return false;
    if (sport && c.sport !== sport) return false;
    if (market && c.market_type !== market) return false;
    if (surebetOnly && !c.is_surebet) return false;
    return true;
  });
}

function groupStatusPill(g) {
  return g.anySurebet
    ? '<span class="pill pill-surebet">Surebet</span>'
    : '<span class="pill pill-none">Sin arbitraje</span>';
}

function groupMarginClass(g) {
  if (g.anySurebet) return "margin-positive";
  if (g.bestMargin > 0) return "margin-amber";
  return "margin-negative";
}

function groupRowClass(g) {
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
      <td>${g.sport}</td>
      <td>${single ? g.markets[0].market_type : `${g.markets.length} mercados`}</td>
      <td>${g.bookmakers.map(bookmakerSpan).join(", ")}</td>
      <td class="odds-cell">${single ? oddsSummary(g.markets[0].odds) : "Ver detalle ▸"}</td>
      <td class="margin-value ${groupMarginClass(g)}">${pct(g.bestMargin)}</td>
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
        <td>${m.market_type}</td>
        <td>${bookmakersCell(m.bookmakers)}</td>
        <td class="odds-cell">${oddsSummary(m.odds)}</td>
        <td class="margin-value ${marginClass(m)}">${pct(m.margin)}</td>
        <td>${
          m.is_surebet
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
    margin: (g) => g.bestMargin,
    last_seen_at: (g) => new Date(g.lastSeenAt).getTime(),
  };
  const getValue = keyed[sortKey] || keyed.margin;
  return [...groups].sort((a, b) => {
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

function render(data) {
  state.comparisons = data.comparisons;
  renderStats(data);
  renderActiveTable(data);
  renderAllTable(data);
  renderHistoryTable(data);

  const generated = data.generated_at ? new Date(data.generated_at) : null;
  document.getElementById("last-updated").textContent = generated
    ? `Actualizado ${timeAgo(data.generated_at)} (${generated.toLocaleString("es-ES")})`
    : "Sin datos todavía — esperando al primer escaneo";
}

async function load() {
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
  ["filter-search", "filter-sport", "filter-market", "filter-surebet-only"].forEach((id) => {
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
        state.sortDir = "desc";
      }
      if (window.__surebetsData) renderAllTable(window.__surebetsData);
    });
  });

  document.querySelector("#active-table tbody").addEventListener("click", (e) => toggleGroupRow(e, renderActiveTable));
  document.querySelector("#all-table tbody").addEventListener("click", (e) => toggleGroupRow(e, renderAllTable));
}

wireControls();
load();
setInterval(load, AUTO_REFRESH_MS);
