const DATA_URL = "data.json";
const AUTO_REFRESH_MS = 60_000;

let state = {
  comparisons: [],
  sortKey: "margin",
  sortDir: "desc",
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
  return odds.map((o) => `${o.name}: ${o.bookmaker} @${o.odds.toFixed(2)}`).join(" · ");
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

function renderActiveTable(data) {
  const active = data.comparisons
    .filter((c) => c.is_surebet)
    .sort((a, b) => b.margin - a.margin);

  document.getElementById("active-count").textContent = active.length;
  const tbody = document.querySelector("#active-table tbody");
  const empty = document.getElementById("active-empty");

  if (!active.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  tbody.innerHTML = active
    .map(
      (row) => `
      <tr class="row-surebet">
        <td class="event-cell">${row.event}</td>
        <td>${row.sport}</td>
        <td>${row.market_type}</td>
        <td>${row.bookmakers}</td>
        <td class="odds-cell">${oddsSummary(row.odds)}</td>
        <td class="margin-value margin-positive">${pct(row.margin)}</td>
        <td>${money(row.guaranteed_profit)}</td>
        <td>${timeAgo(row.last_seen_at)}</td>
      </tr>`
    )
    .join("");
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

function sortRows(rows) {
  const { sortKey, sortDir } = state;
  const dir = sortDir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === "string") return av.localeCompare(bv) * dir;
    return (av - bv) * dir;
  });
}

function renderAllTable(data) {
  populateFilterOptions(data);
  const filtered = sortRows(applyFilters(data.comparisons));

  document.getElementById("all-count").textContent = `${filtered.length} / ${data.comparisons.length}`;
  const tbody = document.querySelector("#all-table tbody");
  const empty = document.getElementById("all-empty");

  if (!filtered.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  tbody.innerHTML = filtered
    .map(
      (row) => `
      <tr class="${rowClass(row)}">
        <td class="event-cell">${row.event}</td>
        <td>${row.sport}</td>
        <td>${row.market_type}</td>
        <td>${row.bookmakers}</td>
        <td class="odds-cell">${oddsSummary(row.odds)}</td>
        <td class="margin-value ${marginClass(row)}">${pct(row.margin)}</td>
        <td>${
          row.is_surebet
            ? '<span class="pill pill-surebet">Surebet</span>'
            : '<span class="pill pill-none">Sin arbitraje</span>'
        }</td>
        <td>${timeAgo(row.last_seen_at)}</td>
      </tr>`
    )
    .join("");
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
        <td>${row.bookmakers}</td>
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
}

wireControls();
load();
setInterval(load, AUTO_REFRESH_MS);
