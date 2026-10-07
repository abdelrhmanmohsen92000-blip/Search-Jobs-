/* Career Hunter dashboard (V1.6) — vanilla JS, no build step, no external libraries.
 * All data is inserted with textContent (never innerHTML): job titles and company
 * names come from the web and are treated as untrusted text. */
"use strict";

const main = document.getElementById("main");
const tooltip = document.getElementById("tooltip");
const SVGNS = "http://www.w3.org/2000/svg";

// ---------------------------------------------------------------- helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid) el.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
  return el;
}
async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", "X-Career-Hunter": "1" },
  };
  const res = await fetch("/api/" + path, opts);
  const data = await res.json().catch(() => ({ error: "Bad response" }));
  if (!res.ok) { const err = new Error(data.error || res.statusText); err.status = res.status; throw err; }
  return data;
}
function toast(msg) {
  const t = h("div", { class: "toast", role: "status", text: msg });
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}
const num = (v, d = 0) => (v === null || v === undefined || v === "" || isNaN(v)) ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
const unk = (v) => (v === null || v === undefined || v === "") ? "UNKNOWN" : v;
function safeUrl(u) {
  try { const url = new URL(u); return (url.protocol === "https:" || url.protocol === "http:") ? url.href : null; }
  catch { return null; }
}
function link(u, text) {
  const href = safeUrl(u);
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text: text || href }) : h("span", { class: "muted", text: unk(u) });
}
const DECISION_LABEL = { APPLY_NOW: "Apply now", APPLY: "Apply", REVIEW: "Review", NETWORK_FIRST: "Network first", WATCH: "Watch", SKIP: "Skip" };
const DECISION_ICON = { APPLY_NOW: "🔥", APPLY: "🟢", REVIEW: "🟡", NETWORK_FIRST: "🔵", WATCH: "⚪", SKIP: "🔴" };
function decisionChip(d) {
  return h("span", { class: "chip decision", title: d || "" }, (DECISION_ICON[d] || "") + " " + (DECISION_LABEL[d] || d || "—"));
}
function chip(text, cls) { return h("span", { class: "chip " + (cls || ""), text }); }
function where(v) { return [v.city, v.country].filter((x) => x && x !== "UNKNOWN").join(", ") || "Location UNKNOWN"; }
function card(title, ...kids) { return h("section", { class: "card" }, title ? h("h2", { text: title }) : null, kids); }
function empty(text) { return h("div", { class: "empty", text }); }
function table(cols, rows, onRow) {
  const thead = h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.num ? "num" : "", text: c.label }))));
  const tbody = h("tbody", {}, rows.map((r) => h("tr", {
    class: onRow ? "clickable" : "", tabindex: onRow ? "0" : null,
    onclick: onRow ? () => onRow(r) : null,
    onkeydown: onRow ? (e) => { if (e.key === "Enter") onRow(r); } : null,
  }, cols.map((c) => h("td", { class: c.num ? "num" : "" }, c.render ? c.render(r) : unk(r[c.key]))))));
  return h("div", { class: "table-wrap" }, h("table", {}, thead, tbody));
}
function go(hash) { location.hash = hash; }

// ---------------------------------------------------------------- tooltip
function showTip(e, value, label) {
  tooltip.replaceChildren(h("strong", { text: value }), h("span", { text: label }));
  tooltip.style.display = "block";
  const r = e.clientX !== undefined && e.clientX !== 0 ? { x: e.clientX, y: e.clientY } :
    (() => { const b = e.target.getBoundingClientRect(); return { x: b.right, y: b.top }; })();
  tooltip.style.left = Math.min(r.x + 12, window.innerWidth - 270) + "px";
  tooltip.style.top = (r.y + 12) + "px";
}
function hideTip() { tooltip.style.display = "none"; }

// ---------------------------------------------------------------- charts
// Horizontal bars: single series in --series-1 unless a row sets `color` (then a legend is required).
function hbar(rows, opts = {}) {
  const fmt = opts.format || ((v) => num(v, 1));
  const draw = (W) => {
    const LW = Math.min(170, Math.max(90, W * 0.32)), PAD = 48, ROW = 28, BAR = 16;
    const max = Math.max(1, ...rows.map((r) => r.value || 0));
    const H = Math.max(ROW, rows.length * ROW) + 6;
    const maxChars = Math.floor((LW - 10) / 6.6);
    const svg = s("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.title || "bar chart" });
    svg.appendChild(s("line", { x1: LW, x2: LW, y1: 0, y2: H, class: "axis" }));
    rows.forEach((r, i) => {
      const y = i * ROW + (ROW - BAR) / 2 + 3;
      const w = Math.max(0, (r.value || 0) / max * (W - LW - PAD));
      const rr = Math.min(4, w / 2, BAR / 2);
      const x0 = LW, x1 = LW + w;
      const d = w <= 0 ? "" : `M${x0},${y} H${x1 - rr} A${rr},${rr} 0 0 1 ${x1},${y + rr} V${y + BAR - rr} A${rr},${rr} 0 0 1 ${x1 - rr},${y + BAR} H${x0} Z`;
      const label = String(r.label);
      const g = s("g", { class: "mark", tabindex: "0", "aria-label": `${label}: ${fmt(r.value)}` },
        s("rect", { class: "hit", x: 0, y: i * ROW + 3, width: W, height: ROW, fill: "transparent" }),
        d ? s("path", { d, fill: r.color || "var(--series-1)" }) : null,
        s("text", { x: LW - 8, y: y + BAR / 2 + 4, "text-anchor": "end", class: "lbl" }, label.length > maxChars ? label.slice(0, maxChars - 1) + "…" : label),
        s("text", { x: x1 + 6, y: y + BAR / 2 + 4, class: "val" }, fmt(r.value)));
      const tip = (e) => showTip(e, fmt(r.value), r.tip || label);
      g.addEventListener("pointermove", tip); g.addEventListener("focus", tip);
      g.addEventListener("pointerleave", hideTip); g.addEventListener("blur", hideTip);
      if (opts.onClick) { g.style.cursor = "pointer"; g.addEventListener("click", () => opts.onClick(r)); }
      svg.appendChild(g);
    });
    return svg;
  };
  return chartBox(draw, rows, opts, fmt);
}
// Vertical columns (ordered categories, e.g. score buckets or weeks).
function columns(rows, opts = {}) {
  const fmt = opts.format || ((v) => num(v));
  const draw = (W) => {
    const H = 220, B = 26, T = 18, n = Math.max(1, rows.length);
    const slot = W / n, colW = Math.min(24, slot * 0.6);
    const max = Math.max(1, ...rows.map((r) => r.value || 0));
    const svg = s("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.title || "column chart" });
    svg.appendChild(s("line", { x1: 0, x2: W, y1: H - B, y2: H - B, class: "axis" }));
    rows.forEach((r, i) => {
      const hgt = (r.value || 0) / max * (H - B - T);
      const x = i * slot + (slot - colW) / 2, y = H - B - hgt, rr = Math.min(4, colW / 2, hgt / 2);
      const d = hgt <= 0 ? "" : `M${x},${H - B} V${y + rr} A${rr},${rr} 0 0 1 ${x + rr},${y} H${x + colW - rr} A${rr},${rr} 0 0 1 ${x + colW},${y + rr} V${H - B} Z`;
      const label = String(r.label);
      const g = s("g", { class: "mark", tabindex: "0", "aria-label": `${label}: ${fmt(r.value)}` },
        s("rect", { x: i * slot, y: 0, width: slot, height: H, fill: "transparent" }),
        d ? s("path", { d, fill: "var(--series-1)" }) : null,
        s("text", { x: x + colW / 2, y: y - 5, "text-anchor": "middle", class: "val" }, r.value ? fmt(r.value) : ""),
        s("text", { x: x + colW / 2, y: H - 8, "text-anchor": "middle", class: "lbl" }, slot < 44 && i % 2 ? "" : label));
      const tip = (e) => showTip(e, fmt(r.value), r.tip || label);
      g.addEventListener("pointermove", tip); g.addEventListener("focus", tip);
      g.addEventListener("pointerleave", hideTip); g.addEventListener("blur", hideTip);
      svg.appendChild(g);
    });
    return svg;
  };
  return chartBox(draw, rows, opts, fmt);
}
// Charts draw at their container's real width so text stays 12px at every size.
function chartBox(draw, rows, opts, fmt) {
  if (!rows.length) return empty(opts.empty || "No data yet.");
  const plot = h("div", { class: "plot" });
  let lastW = 0;
  const redraw = () => {
    const W = Math.floor(plot.clientWidth);
    if (W > 0 && W !== lastW) { lastW = W; plot.replaceChildren(draw(W)); }
  };
  new ResizeObserver(redraw).observe(plot);
  const svg = plot;
  const legend = opts.legend ? h("div", { class: "legend" }, opts.legend.map((l) =>
    h("span", {}, h("span", { class: "sw", style: `background:${l.color}` }), l.label))) : null;
  const tv = h("details", { class: "tableview" }, h("summary", { text: "Show table" }),
    table([{ label: opts.labelHeader || "Category", key: "label" }, ...(opts.legend ? [{ label: "Group", key: "group" }] : []),
      { label: opts.valueHeader || "Value", num: true, render: (r) => fmt(r.value) }], rows));
  return h("div", { class: "chart" }, legend, svg, tv);
}
const pairs = (list) => (list || []).map(([label, value]) => ({ label, value }));

// ---------------------------------------------------------------- pages
const pages = {};

pages.overview = async () => {
  const d = await api("overview");
  const t = d.tiles;
  const banners = [];
  if (d.synthetic_jobs) banners.push(h("div", { class: "banner" }, `${d.synthetic_jobs} job(s) here are SYNTHETIC demo data (not real postings). Workspace: ${d.workspace}`));
  if (d.network_mode === "offline") banners.push(h("div", { class: "banner" }, "NETWORK_MODE=offline — no live sources are requested; manual import, analysis and reports still work."));
  const tiles = [
    ["Apply now", t.apply_now, true], ["Active opportunities", t.active], ["Jobs tracked", t.jobs], ["In pipeline", t.in_pipeline],
    ["Interviews", t.interviews], ["Follow-ups due", t.followups_due], ["Networking suggestions", t.open_networking],
    ["Unread notifications", t.unread_notifications],
  ];
  return [
    h("h1", { text: "Overview" }), h("p", { class: "sub", text: "Today's priorities. Every action stays yours — nothing is sent or applied automatically." }),
    banners,
    h("div", { class: "tiles" }, tiles.map(([label, value, hero]) => h("div", { class: "card tile" + (hero ? " hero" : "") },
      h("div", { class: "label", text: label }), h("div", { class: "value", text: num(value) })))),
    h("div", { class: "grid cols-2" },
      card("Top opportunities", jobList(d.top_opportunities)),
      card("Decisions", hbar(d.decisions.map((x) => ({ label: `${DECISION_ICON[x.decision]} ${DECISION_LABEL[x.decision]}`, value: x.count })), { format: (v) => num(v), title: "Jobs by decision" })),
      card("Apply now", jobList(d.apply_now, "Nothing waiting in APPLY NOW.")),
      card("Network first", jobList(d.network_first, "No NETWORK_FIRST opportunities.")),
      card("Follow-ups due", d.followups.length ? h("ul", { class: "list" }, d.followups.map((a) => h("li", {},
        h("a", { href: "#job/" + encodeURIComponent(a.opportunity_id), text: `${a.job_title} @ ${a.company}` }), h("div", { class: "small muted", text: `Applied ${unk(a.application_date)} · due ${a.follow_up_date}` })))) : empty("No follow-ups due.")),
      card("Interviews", d.interviews.length ? h("ul", { class: "list" }, d.interviews.map((a) => h("li", {},
        h("a", { href: "#job/" + encodeURIComponent(a.opportunity_id), text: `${a.job_title} @ ${a.company}` }), h("div", { class: "small muted", text: "Date: " + unk(a.interview_date) })))) : empty("No interviews scheduled.")),
      card("Notifications", notificationList(d.notifications)),
      card("Market signals & skill gaps", h("ul", { class: "list" }, d.market_signals.map((x) => h("li", { text: x })),
        d.skills_gaps.map((g) => h("li", {}, h("strong", { text: g.skill }), ` — ${g.status.toLowerCase()}, in ${g.jobs} active job(s)`)))),
    ),
  ];
};
function jobList(list, emptyText) {
  if (!list || !list.length) return empty(emptyText || "No jobs yet.");
  return h("ul", { class: "list" }, list.map((v) => h("li", {},
    h("div", { class: "spread" }, h("a", { href: "#job/" + encodeURIComponent(v.id), text: v.job_title }), decisionChip(v.decision)),
    h("div", { class: "small muted", text: `${v.company} · ${where(v)} · opportunity ${num(v.opportunity_score, 1)} · match ${num(v.overall_match, 1)}` }))));
}
function notificationList(list) {
  if (!list.length) return empty("No unread notifications.");
  return h("div", {}, h("ul", { class: "list" }, list.map((n) => h("li", {},
    h("div", { class: "spread" }, h("strong", { text: n.title }), chip(n.event_type)),
    h("div", { class: "small muted", text: `${n.created_at} · ${n.body}` })))),
  h("button", { class: "btn small", onclick: async () => { await api("notifications/read", {}); render(); }, text: "Mark all read" }));
}

pages.jobs = async (params) => {
  const qs = new URLSearchParams(params);
  const d = await api("jobs?" + qs.toString());
  const f = d.facets;
  const sel = (name, label, options) => h("label", {}, label, h("select", { name, onchange: applyFilters },
    h("option", { value: "", text: "All" }), options.map((o) => h("option", { value: o, text: o, selected: params[name] === o }))));
  const form = h("form", { class: "filters", onsubmit: (e) => { e.preventDefault(); applyFilters(); } },
    h("label", {}, "Search", h("input", { name: "q", value: params.q || "", placeholder: "title, company…" })),
    sel("country", "Country", f.country), sel("city", "City", f.city), sel("role", "Role", f.role_family),
    sel("company", "Company", f.company), sel("employment_type", "Employment", f.employment_type),
    sel("remote", "Remote", ["true", "false"]), sel("freshness", "Freshness", f.freshness), sel("status", "Status", f.status),
    sel("decision", "Decision", f.decision),
    h("label", {}, "Min score", h("input", { name: "min_score", type: "number", min: "0", max: "100", value: params.min_score || "", style: "width:80px" })),
    h("label", {}, "Sort", h("select", { name: "sort", onchange: applyFilters }, [["opportunity_score", "Opportunity"], ["overall_match", "Match"],
      ["confidence", "Confidence"], ["date_found", "Date found"], ["date_posted", "Date posted"], ["company", "Company"], ["job_title", "Title"]]
      .map(([v, l]) => h("option", { value: v, text: l, selected: (params.sort || "opportunity_score") === v })))),
    h("label", {}, "Order", h("select", { name: "order", onchange: applyFilters }, h("option", { value: "desc", text: "High → low", selected: params.order !== "asc" }), h("option", { value: "asc", text: "Low → high", selected: params.order === "asc" }))),
    h("button", { class: "btn", type: "submit", text: "Apply" }),
    h("button", { class: "btn", type: "button", onclick: () => go("#jobs"), text: "Reset" }));
  function applyFilters() {
    const p = new URLSearchParams();
    for (const el of form.elements) if (el.name && el.value) p.set(el.name, el.value);
    go("#jobs" + (p.toString() ? "?" + p.toString() : ""));
  }
  return [h("h1", { text: "Jobs" }), h("p", { class: "sub", text: `${d.count} of ${d.total} jobs` }), form,
    card(null, d.jobs.length ? table([
      { label: "Decision", render: (v) => decisionChip(v.decision) },
      { label: "Title", render: (v) => h("span", {}, v.job_title, v.synthetic ? h("span", { class: "small muted", text: " · synthetic" }) : null) },
      { label: "Company", key: "company" }, { label: "Location", render: where },
      { label: "Type", key: "employment_type" }, { label: "Opportunity", num: true, render: (v) => num(v.opportunity_score, 1) },
      { label: "Match", num: true, render: (v) => num(v.overall_match, 1) }, { label: "Confidence", num: true, render: (v) => num(v.confidence) },
      { label: "Freshness", key: "freshness" }, { label: "Status", key: "status" },
    ], d.jobs, (v) => go("#job/" + encodeURIComponent(v.id))) : empty("No jobs match these filters."))];
};

pages.job = async (params, id) => {
  const d = await api("jobs/" + encodeURIComponent(id));
  const v = d.job, a = d.analysis, p = d.packet, req = a.requirements || {}, gap = a.skills_gap || {};
  const dims = a.dimensions || {};
  const DIM_LABEL = { profile_match: "Profile match", skills_match: "Skills", experience_match: "Experience", location_match: "Location",
    employment_match: "Employment", company_quality: "Company quality", career_growth: "Career growth", compensation: "Compensation",
    freshness: "Freshness", application_difficulty: "Application difficulty (higher = harder)", networking_value: "Networking value",
    strategic_value: "Strategic career value" };
  const statusSel = h("select", { "aria-label": "Move to status" }, d.allowed_statuses.map((st) => h("option", { value: st, text: st, selected: st === v.status })));
  const fbButtons = [["application", "I applied"], ["interview", "Got an interview"], ["rejection", "Rejected"], ["offer", "Got an offer"],
    ["no_response", "No response"], ["withdrawn", "I withdrew"]].map(([kind, label]) => h("button", { class: "btn small", text: label,
    onclick: async () => {
      const reason = ["rejection", "withdrawn"].includes(kind) ? prompt("Reason (optional) — e.g. missing GCC experience") : "";
      if (reason === null) return;
      await post("feedback", { kind, job_id: v.id, reason }, "Feedback recorded");
    } }));
  const rate = (rating) => h("button", { class: "btn small", text: rating === "good" ? "👍 Good match" : "👎 Bad match", onclick: async () => {
    const reason = prompt("Why? (optional)"); if (reason === null) return;
    await post("feedback", { kind: "job", job_id: v.id, rating, reason }, "Thanks — rating recorded");
  } });
  const fieldSources = (d.provenance.field_sources || {});
  const reqRow = (label, key, value) => h("tr", {}, h("th", { text: label }), h("td", {}, Array.isArray(value) ? (value.length ? value.join(", ") : "—") : unk(value)),
    h("td", { class: "small muted", text: fieldSources[key] || "" }));
  const salary = req.salary && typeof req.salary === "object" ? `${req.salary.salary_min ?? "?"}–${req.salary.salary_max ?? "?"} ${req.salary.salary_currency}/${req.salary.salary_period}` : unk(req.salary);
  return [
    h("p", {}, h("a", { href: "#jobs", text: "← Jobs" })),
    h("div", { class: "spread" }, h("h1", { text: v.job_title }), decisionChip(a.decision)),
    h("p", { class: "sub" }, `${v.company} · ${where(v)} · ${unk(v.employment_type)} · status ${v.status}`, v.synthetic ? " · SYNTHETIC demo job" : ""),
    h("div", { class: "tiles" }, [["Overall match", a.overall_match], ["Opportunity score", a.opportunity_score], ["Confidence", a.confidence]].map(([l, val]) =>
      h("div", { class: "card tile" }, h("div", { class: "label", text: l }), h("div", { class: "value", text: num(val, 1) })))),
    h("div", { class: "grid cols-2" },
      card("Why", h("ul", {}, (a.reasons || []).map((r) => h("li", { text: r }))), h("p", {}, h("strong", { text: "Recommendation: " }), a.recommendation),
        h("p", { class: "small muted", text: `Model version ${a.model_version} · sub-scores ${a.sub_scores_source} · analysis ${a.stored ? "stored" : "computed now"}` })),
      card("Risks", h("ul", {}, (a.risks || []).map((r) => h("li", { text: r })))),
      card("Dimensions", Object.keys(DIM_LABEL).map((k) => h("div", { class: "meter" }, h("span", { class: "small", text: DIM_LABEL[k] }),
        h("div", { class: "track" }, h("div", { class: "fill", style: `width:${Math.max(0, Math.min(100, dims[k] || 0))}%` })), h("span", { class: "v", text: num(dims[k]) })))),
      card("Skills gap",
        h("h3", { text: "Matched" }), h("div", { class: "row" }, (gap.matched || []).map((x) => chip("✓ " + x, "status-good")), !(gap.matched || []).length && "—"),
        h("h3", { text: "Transferable" }), h("div", { class: "row" }, (gap.transferable || []).map((x) => chip(`≈ ${x.skill} (via ${x.via.join("/")})`)), !(gap.transferable || []).length && "—"),
        h("h3", { text: "Missing" }), h("div", { class: "row" }, (gap.missing || []).map((x) => chip("✗ " + x)), !(gap.missing || []).length && "—"),
        h("h3", { text: "Preferred, not demonstrated" }), h("div", { class: "row" }, (gap.preferred_missing || []).map((x) => chip(x)), !(gap.preferred_missing || []).length && "—")),
      card("Application packet",
        h("table", {}, h("tbody", {},
          h("tr", {}, h("th", { text: "Apply at" }), h("td", {}, link(p.application_url), h("div", { class: "small muted", text: p.application_url_source }))),
          h("tr", {}, h("th", { text: "Job page" }), h("td", {}, link(p.job.job_page_url))),
          h("tr", {}, h("th", { text: "Deadline" }), h("td", { text: p.deadline })),
          h("tr", {}, h("th", { text: "CV" }), h("td", { text: `${p.cv_version.id} — ${p.cv_version.label || ""} (file: ${p.cv_version.file})` })),
          h("tr", {}, h("th", { text: "Portfolio" }), h("td", { text: `${p.portfolio.id} — ${p.portfolio.label || ""}` })),
          h("tr", {}, h("th", { text: "Project examples" }), h("td", { text: Array.isArray(p.portfolio.project_examples) ? p.portfolio.project_examples.map((e) => e.project).join(", ") || "—" : p.portfolio.project_examples })),
          h("tr", {}, h("th", { text: "Cover letter" }), h("td", { text: `${p.cover_letter.requirement} — ${p.cover_letter.why}` })),
          h("tr", {}, h("th", { text: "Lead with" }), h("td", { text: p.key_skills.lead_with.join(", ") || "—" })),
          h("tr", {}, h("th", { text: "Do not claim" }), h("td", { text: p.key_skills.do_not_claim.join(", ") || "—" })))),
        h("p", { class: "small muted", text: "Nothing is submitted for you — apply yourself, then record it below." })),
      card("Pipeline",
        h("div", { class: "row" }, statusSel, h("button", { class: "btn primary", text: "Move", onclick: () => moveJob(v.id, statusSel.value) })),
        h("h3", { text: "Record an outcome" }), h("div", { class: "row" }, fbButtons), h("div", { class: "row", style: "margin-top:6px" }, rate("good"), rate("bad")),
        h("h3", { text: "History" }), d.history.length ? h("ul", { class: "list small" }, d.history.map((e) => h("li", { text: `${e.at} · ${e.from_status} → ${e.to_status} · ${e.actor}${e.note ? " · " + e.note : ""}` }))) : empty("No moves yet.")),
      card("Networking (drafts only)", networkingList(d.networking)),
      card("Extracted requirements", h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "Field" }), h("th", { text: "Value" }), h("th", { text: "Source" }))), h("tbody", {},
        reqRow("Required skills", "required_skills", req.required_skills), reqRow("Preferred skills", "preferred_skills", req.preferred_skills),
        reqRow("Software", "software", req.software), reqRow("Years of experience", "min_years_experience", req.min_years_experience),
        reqRow("Education", "education", req.education), reqRow("Certifications", "certifications", req.certifications),
        reqRow("Languages", "languages", req.languages), reqRow("Work mode", "work_mode", req.work_mode),
        reqRow("Employment type", "employment_type", req.employment_type), reqRow("Seniority", "seniority", req.seniority),
        reqRow("Salary", "salary", salary), reqRow("Benefits", "benefits", req.benefits), reqRow("Department", "department", req.department),
        reqRow("Application method", "application_method", req.application_method), reqRow("Eligibility barriers", "eligibility_barriers", req.eligibility_barriers)))),
        h("p", { class: "small muted", text: `Source ${d.provenance.source} · retrieved ${unk(d.provenance.retrieved_at)} · ${unk(d.provenance.extraction_method)}. UNKNOWN means the posting does not say.` })),
      card("Posting text", d.description ? h("div", { class: "desc", text: d.description }) : empty("Posting text was not stored for this job.")),
    ),
  ];
};
async function post(path, body, okMsg) {
  try { await api(path, body); toast(okMsg); render(); }
  catch (e) { toast("Error: " + e.message); }
}
async function moveJob(id, status, force) {
  try {
    await api(`applications/${encodeURIComponent(id)}/move`, { status, force: !!force });
    toast(`Moved to ${status}`); render();
  } catch (e) {
    if (e.status === 409 && /force/.test(e.message) && confirm(e.message + "\n\nReopen it anyway?")) return moveJob(id, status, true);
    toast("Error: " + e.message);
  }
}
function networkingList(actions) {
  if (!actions.length) return empty("No networking actions suggested for this job.");
  return h("ul", { class: "list" }, actions.map((a) => h("li", {},
    h("div", { class: "spread" }, h("strong", { text: `${a.contact_type} · ${a.company}` }), chip(`${a.priority} · ${a.status}`)),
    a.known_contact ? h("div", { class: "small", text: "Known contact: " + a.known_contact }) : null,
    h("div", { class: "small", text: "Why: " + a.reason }), h("div", { class: "small", text: "Angle: " + a.outreach_angle }),
    h("div", { class: "draft", text: a.draft_message }),
    h("div", { class: "row" },
      h("button", { class: "btn small", text: "Copy draft", onclick: () => copy(a.draft_message) }),
      [["APPROVED", "Approve draft"], ["DONE", "I sent it myself"], ["REPLIED", "Got a reply"], ["NO_RESPONSE", "No response"], ["DISMISSED", "Dismiss"]]
        .map(([st, label]) => h("button", { class: "btn small", text: label, onclick: () => post(`networking/${encodeURIComponent(a.action_id)}/status`, { status: st }, `Marked ${st}`) }))))));
}
function copy(text) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast("Draft copied — review it, then send it yourself"), () => toast("Copy failed — select the text manually"));
}

pages.opportunities = async () => {
  const d = await api("opportunities");
  return [h("h1", { text: "Opportunities" }), h("p", { class: "sub", text: "Active jobs worth effort, grouped by decision." }),
    h("div", { class: "grid cols-2" }, d.groups.map((g) => card(`${DECISION_ICON[g.decision]} ${DECISION_LABEL[g.decision]} (${g.jobs.length})`,
      g.jobs.length ? h("ul", { class: "list" }, g.jobs.map((v) => h("li", {},
        h("div", { class: "spread" }, h("a", { href: "#job/" + encodeURIComponent(v.id), text: v.job_title }), h("span", { class: "small", text: `opp ${num(v.opportunity_score, 1)}` })),
        h("div", { class: "small muted", text: `${v.company} · ${where(v)} · ${v.status}` }),
        h("div", { class: "small", text: (v.matched_skills.length ? "✓ " + v.matched_skills.slice(0, 4).join(", ") : "") + (v.missing_skills.length ? "  ✗ " + v.missing_skills.join(", ") : "") })))) : empty("None."))))];
};

pages.companies = async () => {
  const d = await api("companies");
  return [h("h1", { text: "Companies" }), h("p", { class: "sub", text: "Grades: " + d.grades.map((g) => `${g.grade} ${g.label}`).join(" · ") + ". Override in config/company_overrides.yaml." }),
    card(null, table([
      { label: "Grade", render: (c) => chip(`${c.grade} ${c.grade_label}${c.manual_override ? " (manual)" : ""}`) },
      { label: "Company", key: "company" }, { label: "Score", num: true, render: (c) => num(c.company_score, 1) },
      { label: "Active", num: true, key: "active_opportunities" }, { label: "Jobs", num: true, key: "job_count" },
      { label: "Hiring trend", key: "hiring_trend" }, { label: "Avg match", num: true, render: (c) => num(c.average_match, 1) },
      { label: "Countries", render: (c) => c.countries.join(", ") || "UNKNOWN" }, { label: "Target", render: (c) => c.is_target ? `yes (${c.target_priority})` : "no" },
    ], d.companies, (c) => go("#company/" + encodeURIComponent(c.company_id))))];
};

pages.company = async (params, id) => {
  const d = await api("companies/" + encodeURIComponent(id));
  const c = d.company;
  const fact = (l, val) => h("tr", {}, h("th", { text: l }), h("td", {}, val instanceof Node ? val : unk(val)));
  return [h("p", {}, h("a", { href: "#companies", text: "← Companies" })), h("h1", { text: c.company }),
    h("p", { class: "sub", text: `Grade ${c.grade} ${c.grade_label} · score ${c.company_score}${c.manual_override ? " · manual override" : ""}` }),
    h("div", { class: "grid cols-2" },
      card("Facts (observed only)", h("table", {}, h("tbody", {}, fact("Industry", c.industry), fact("Size", c.size), fact("Website", link(c.website)),
        fact("Careers page", link(c.careers_page)), fact("Countries", c.countries.join(", ") || null), fact("Hiring trend", c.hiring_trend),
        fact("Active opportunities", String(c.active_opportunities)), fact("Average match", c.average_match), fact("Known contacts", c.contacts.join(", ") || "none logged"),
        fact("Notes", c.notes || "—"))), h("p", { class: "small muted", text: "UNKNOWN = not observed; company facts are never invented." })),
      card("Jobs", jobList(d.jobs)),
      card("Networking", networkingList(d.networking)))];
};

pages.applications = async () => {
  const d = await api("applications");
  const funnelRows = ["SHORTLISTED", "READY", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED"].map((st) => ({ label: st, value: d.funnel[st] || 0, tip: `${st}: jobs that ever reached this stage` }));
  const board = h("div", { class: "kanban" }, d.columns.map((col) => {
    const colEl = h("div", { class: "kcol", "data-status": col },
      h("h3", {}, h("span", { text: col }), h("span", { class: "muted", text: String(d.board[col].length) })),
      d.board[col].map((c) => h("div", { class: "kcard", draggable: "true", ondragstart: (e) => e.dataTransfer.setData("text/plain", c.job_id) },
        h("a", { class: "t", href: "#job/" + encodeURIComponent(c.job_id), text: c.job_title }),
        h("div", { class: "small muted", text: `${c.company} · ${c.country}` }),
        h("div", { class: "small", text: `${c.decision || "—"} · opp ${num(c.opportunity_score, 1)}${c.follow_up_date ? " · follow-up " + c.follow_up_date : ""}` }),
        h("select", { "aria-label": `Move ${c.job_title}`, onchange: (e) => e.target.value && moveJob(c.job_id, e.target.value) },
          h("option", { value: "", text: "Move to…" }), d.statuses.filter((st) => st !== c.status).map((st) => h("option", { value: st, text: st }))))));
    colEl.addEventListener("dragover", (e) => { e.preventDefault(); colEl.classList.add("drop"); });
    colEl.addEventListener("dragleave", () => colEl.classList.remove("drop"));
    colEl.addEventListener("drop", (e) => { e.preventDefault(); colEl.classList.remove("drop"); const id = e.dataTransfer.getData("text/plain"); if (id) moveJob(id, col); });
    return colEl;
  }));
  return [h("h1", { text: "Applications" }), h("p", { class: "sub", text: "Drag a card (or use “Move to…”) — every move is saved with a timestamp. Applying itself is always done by you." }),
    card("Pipeline", board),
    h("div", { class: "grid cols-2", style: "margin-top:14px" },
      card("Application funnel", hbar(funnelRows, { format: (v) => num(v), title: "Application funnel", labelHeader: "Stage", valueHeader: "Jobs" })),
      card("Recent moves", d.recent_events.length ? h("ul", { class: "list small" }, d.recent_events.map((e) => h("li", { text: `${e.at} · ${e.job_id} · ${e.from_status} → ${e.to_status} · ${e.actor}` }))) : empty("No moves yet.")),
      card("Closed / withdrawn", d.closed.length ? jobList(d.closed.map((c) => ({ ...c, id: c.job_id, city: "", overall_match: null }))) : empty("None.")))];
};

pages.networking = async () => {
  const d = await api("networking");
  return [h("h1", { text: "Networking" }), h("p", { class: "sub", text: d.policy }),
    h("div", { class: "row", style: "margin-bottom:12px" }, Object.entries(d.by_status).map(([k, v]) => chip(`${k}: ${v}`))),
    h("div", { class: "grid cols-2" },
      card(`Follow-ups due (${d.followups_due.length})`, networkingList(d.followups_due)),
      card(`Suggested actions (${d.open.length})`, networkingList(d.open)))];
};

pages.interviews = async () => {
  const d = await api("interviews");
  return [h("h1", { text: "Interviews" }), h("div", { class: "grid cols-2" },
    card("Upcoming", d.upcoming.length ? h("ul", { class: "list" }, d.upcoming.map((a) => h("li", {},
      h("a", { href: "#job/" + encodeURIComponent(a.opportunity_id), text: `${a.job_title} @ ${a.company}` }),
      h("div", { class: "small muted", text: "Date: " + unk(a.interview_date) + " — set it with: career_hunter.py application " + a.opportunity_id + " --interview-date YYYY-MM-DD" })))) : empty("No interviews scheduled.")),
    card("Interview funnel", hbar(d.funnel.map((f) => ({ label: f.stage, value: f.count })), { format: (v) => num(v), title: "Interview funnel", labelHeader: "Stage", valueHeader: "Jobs" })),
    card("Offers", d.offers.length ? h("ul", { class: "list" }, d.offers.map((a) => h("li", { text: `${a.job_title} @ ${a.company}` }))) : empty("No offers yet.")))];
};

pages.skills = async () => {
  const d = await api("skills");
  const COLORS = { MATCHED: "var(--series-1)", TRANSFERABLE: "var(--series-2)", MISSING: "var(--series-3)" };
  const rows = d.demand.slice(0, 15).map((r) => ({ label: r.skill, value: r.demand_score, color: COLORS[r.status], group: r.status,
    tip: `${r.skill} — ${r.status.toLowerCase()} · required in ${r.required_in}, preferred in ${r.preferred_in}` }));
  return [h("h1", { text: "Skills" }), h("p", { class: "sub", text: `Demand across ${d.active_jobs} active job(s). ${d.note}` }),
    h("div", { class: "grid cols-2" },
      card("Skill demand (required ×2 + preferred)", hbar(rows, { format: (v) => num(v), title: "Skill demand", labelHeader: "Skill", valueHeader: "Demand",
        legend: [{ label: "You have it", color: COLORS.MATCHED }, { label: "Transferable", color: COLORS.TRANSFERABLE }, { label: "Missing", color: COLORS.MISSING }] })),
      card("Priority learning", d.priority_learning.length ? table([{ label: "Skill", key: "skill" }, { label: "Status", key: "status" },
        { label: "Required in", num: true, key: "required_in" }, { label: "Avg opp.", num: true, key: "avg_opportunity" },
        { label: "Would help with", render: (r) => r.unlocks.slice(0, 3).join(", ") || "—" }], d.priority_learning) : empty("No gaps in active jobs.")),
      card("You already have (most demanded)", h("div", { class: "row" }, d.matched.slice(0, 20).map((r) => chip(`✓ ${r.skill} · ${r.jobs}`)))),
      card("Transferable", h("div", { class: "row" }, d.transferable.map((r) => chip(`≈ ${r.skill} · ${r.jobs}`)), !d.transferable.length && "—")))];
};

pages.market = async () => {
  const d = await api("market");
  return [h("h1", { text: "Market" }), h("p", { class: "sub", text: `${d.total_jobs} jobs tracked, ${d.active_jobs} active. Remote share ${d.remote_share ?? "UNKNOWN"}%.` }),
    h("div", { class: "grid cols-2" },
      card("Signals", h("ul", { class: "list" }, d.signals.map((x) => h("li", { text: x })))),
      card("Opportunity score distribution", columns(pairs(d.opportunity_distribution), { title: "Opportunity score distribution", labelHeader: "Score", valueHeader: "Jobs" })),
      card("Active jobs by country", hbar(pairs(d.by_country), { format: (v) => num(v), labelHeader: "Country", valueHeader: "Jobs", onClick: (r) => go("#jobs?country=" + encodeURIComponent(r.label)) })),
      card("Active jobs by role", hbar(pairs(d.by_role), { format: (v) => num(v), labelHeader: "Role", valueHeader: "Jobs", onClick: (r) => go("#jobs?role=" + encodeURIComponent(r.label)) })),
      card("Active jobs by company", hbar(pairs(d.by_company), { format: (v) => num(v), labelHeader: "Company", valueHeader: "Jobs", onClick: (r) => go("#jobs?company=" + encodeURIComponent(r.label)) })),
      card("Jobs found per week", columns(pairs(d.jobs_found_by_week), { title: "Jobs found per week", labelHeader: "Week", valueHeader: "Jobs" })),
      card("Employment type", hbar(pairs(d.by_employment_type), { format: (v) => num(v), labelHeader: "Type", valueHeader: "Jobs" })),
      card("Posted salaries", h("p", { class: "small muted", text: d.salary_note }), Object.keys(d.posted_salaries).length ? table([{ label: "Currency / period", key: "k" },
        { label: "n", num: true, key: "n" }, { label: "Min", num: true, render: (r) => num(r.min) }, { label: "Median", num: true, render: (r) => num(r.median) }, { label: "Max", num: true, render: (r) => num(r.max) }],
        Object.entries(d.posted_salaries).map(([k, v]) => ({ k, ...v }))) : empty("No salaries posted.")),
      card("Top companies", d.top_companies.length ? table([{ label: "Grade", key: "grade" }, { label: "Company", key: "company" },
        { label: "Active", num: true, key: "active_opportunities" }, { label: "Trend", key: "hiring_trend" }], d.top_companies, (c) => go("#company/" + encodeURIComponent(c.company_id))) : empty("None.")))];
};

pages.sources = async () => {
  const d = await api("sources");
  const hs = d.health;
  return [h("h1", { text: "Sources" }), h("p", { class: "sub", text: `${hs.sources} sources with recorded health.` }),
    h("div", { class: "row", style: "margin-bottom:12px" }, Object.entries(hs.by_state).map(([k, v]) => chip(`${k}: ${v}`))),
    h("div", { class: "grid" },
      card("Health", hs.rows.length ? table([{ label: "Source", key: "source" }, { label: "Health", render: (r) => h("span", { class: r.health_state === "VERIFIED" ? "status-good" : ["BLOCKED", "UNAVAILABLE", "PARSER_FAILED"].includes(r.health_state) ? "status-bad" : "status-warn", text: unk(r.health_state) }) },
        { label: "Last attempt", key: "last_attempt" }, { label: "Last success", key: "last_success" }, { label: "Failures", num: true, key: "consecutive_failures" },
        { label: "Error", key: "error_type" }, { label: "Cooldown until", key: "cooldown_until" }], hs.rows) : empty("No source health recorded yet — run `career_hunter.py research`.")),
      card("Recent research runs", d.runs.length ? table([{ label: "Started", key: "started_at" }, { label: "Status", key: "status" }, { label: "Network", key: "network_mode" },
        { label: "Requests", num: true, key: "requests" }, { label: "Raw", num: true, key: "raw_results" }, { label: "New", num: true, key: "new_opportunities" },
        { label: "Blocked", render: (r) => (r.sources_blocked || []).join(", ") || "—" }], d.runs) : empty("No research runs yet.")),
      card("Registry", table([{ label: "Source", key: "name" }, { label: "Implementation", key: "implementation" }, { label: "Enabled", render: (r) => String(r.enabled) },
        { label: "Credential", render: (r) => r.credential_env ? `${r.credential_env}: ${r.credential_present ? "set" : "not set"}` : "—" }], d.registry)))];
};

pages.settings = async () => {
  const d = await api("settings");
  return [h("h1", { text: "Settings" }), h("p", { class: "sub", text: `Workspace ${d.workspace} · NETWORK_MODE=${d.network_mode} · timezone ${d.timezone} · goal ${d.career_goal}` }),
    h("div", { class: "grid cols-2" },
      card("Environment (values never shown)", table([{ label: "Variable", key: "k" }, { label: "Status", key: "v" }, { label: "Purpose", key: "help" }],
        Object.entries(d.environment).map(([k, v]) => ({ k, v, help: d.environment_help[k] })))),
      card("Schedules", table([{ label: "Job", key: "id" }, { label: "Cron", key: "cron" }, { label: "Enabled", render: (r) => String(r.enabled) },
        { label: "Next run", key: "next_run" }, { label: "Last run", key: "last_run" }, { label: "Last status", key: "last_status" }], d.schedules),
        h("p", { class: "small muted", text: "Drive with cron/Task Scheduler (`career_hunter.py schedule cron`), `schedule daemon`, or a cloud scheduler calling `schedule run-due`." })),
      card("Decision model", h("p", { class: "small", text: `Active version ${d.model.active_version} (${d.model.path})` }),
        table([{ label: "Version", render: (m) => m.version + (m.active ? " (active)" : "") }, { label: "Created", key: "created_at" }, { label: "By", key: "created_by" }, { label: "Notes", key: "notes" }], d.model.versions),
        h("p", { class: "small muted", text: "Switch with: career_hunter.py config --model-version <version>" })),
      card("Learning loop", h("p", {}, h("strong", { text: d.learning.status + ": " }), d.learning.message || ""),
        h("p", { class: "small", text: `${d.learning.outcomes} outcome(s); suggestions start at ${d.learning.min_outcomes}.` }),
        d.suggestions.length ? h("ul", { class: "list" }, d.suggestions.map((sg) => h("li", {},
          h("div", { class: "spread" }, h("strong", { text: `${sg.suggestion_id} → model ${sg.proposed_version}` }), chip(sg.status)),
          h("ul", { class: "small" }, sg.rationale.map((r) => h("li", { text: r }))),
          sg.includes_synthetic ? h("div", { class: "small muted", text: "Learned from SYNTHETIC outcomes." }) : null,
          sg.status === "PENDING_APPROVAL" ? h("div", { class: "draft small", text: `career_hunter.py learning approve ${sg.suggestion_id} --activate\ncareer_hunter.py learning reject ${sg.suggestion_id} --reason "..."` }) : null))) : empty("No learning suggestions yet."),
        h("p", { class: "small muted", text: "Weights never change silently: a suggestion becomes a new model version only when you approve it on the CLI." })),
      card("Notification channels", table([{ label: "Channel", key: "k" }, { label: "Enabled", render: (r) => String(!!r.enabled) }, { label: "Mode", render: (r) => r.mode || r.url_env || "—" }],
        Object.entries(d.notifications || {}).map(([k, v]) => ({ k, ...v })))),
      card("Always requires your approval", h("ul", {}, d.human_approval.map((x) => h("li", { text: x })))))];
};

// ---------------------------------------------------------------- router
function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "overview";
  const [pathPart, query] = raw.split("?");
  const [page, ...rest] = pathPart.split("/");
  return { page, id: rest.length ? decodeURIComponent(rest.join("/")) : null, params: Object.fromEntries(new URLSearchParams(query || "")) };
}
async function render() {
  const { page, id, params } = parseHash();
  const fn = pages[page] || pages.overview;
  const navKey = { job: "jobs", company: "companies" }[page] || page;
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.getAttribute("href") === "#" + navKey) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  main.style.opacity = "0.6";
  try {
    const content = await fn(params, id);
    main.replaceChildren(...[content].flat(Infinity).filter(Boolean));
  } catch (e) {
    main.replaceChildren(h("h1", { text: "Something went wrong" }), h("p", { text: e.message }));
  }
  main.style.opacity = "1";
  hideTip();
}
window.addEventListener("hashchange", () => { render(); main.focus({ preventScroll: true }); });

// theme
const themeSel = document.getElementById("theme");
function applyTheme(v) { if (v) document.documentElement.setAttribute("data-theme", v); else document.documentElement.removeAttribute("data-theme"); }
try { themeSel.value = localStorage.getItem("ch-theme") || ""; } catch { themeSel.value = ""; }
applyTheme(themeSel.value);
themeSel.addEventListener("change", () => { applyTheme(themeSel.value); try { localStorage.setItem("ch-theme", themeSel.value); } catch { /* storage unavailable */ } });

render();
