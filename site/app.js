const CAUSE_TEXT = {
  stalled_vehicle: "Stalled vehicle",
  pedestrian_obstruction: "Pedestrian in carriageway",
  animal_obstruction: "Animal in carriageway",
  unknown: "Unknown",
};

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
};

const fmt = (n, d = 1) => (n === null || n === undefined ? "–" : Number(n).toFixed(d));
const pct = (n) => `${Math.round(n * 100)}%`;

function truthText(t) {
  if (!t.congestion) return "No sustained congestion";
  if (!t.cause_type) return "Congestion with no attributable subject (expected: unknown)";
  return `${CAUSE_TEXT[t.cause_type] || t.cause_type}, stopped at ${fmt(t.cause_stop_time)} s`;
}

function finding(s) {
  const ev = s.evaluation;
  const c = s.cause;
  const box = document.getElementById("finding");
  box.replaceChildren();
  box.append(el("h3", {}, "Pipeline conclusion"));
  if (!s.congestion.detected) {
    box.append(el("div", { class: "big" }, "No sustained congestion"));
  } else if (c.suspected_track_id === null || c.suspected_track_id === undefined) {
    box.append(el("div", { class: "big" }, "Cause: unknown"));
    box.append(el("p", { class: "explain" }, c.explanation || ""));
  } else {
    box.append(el("div", { class: "big" }, `${CAUSE_TEXT[c.type] || c.type}: track #${c.suspected_track_id}`));
    box.append(el("p", { class: "explain" }, c.explanation || ""));
  }
  const kv = el("dl", { class: "kv" });
  const row = (k, v) => kv.append(el("dt", {}, k), el("dd", {}, v));
  if (s.congestion.detected) {
    row("Congestion from", `${fmt(s.congestion.start_seconds)} s`);
    row("Peak queue", s.congestion.peak_queue_size);
  }
  if (c.suspected_track_id !== null && c.suspected_track_id !== undefined) {
    row("Evidence score", fmt(c.confidence, 2));
    row("Subject stopped", `${fmt(c.first_relevant_timestamp)} s`);
  }
  row("Plate", s.plate && s.plate.text ? s.plate.text : "not read (null)");
  box.append(kv);

  if (s.alternatives && s.alternatives.length) {
    box.append(el("h3", {}, "Ranked candidates"));
    const ol = el("ol", { class: "alts" });
    for (const a of s.alternatives) ol.append(el("li", {}, `#${a.track} ${a.object_type} · ${fmt(a.confidence, 2)}`));
    box.append(ol);
  }

  box.append(el("h3", {}, "Ground truth (simulation)"));
  box.append(el("div", {}, truthText(s.truth)));
  const ok = ev.cause.correct && ev.congestion.detected === ev.congestion.truth;
  box.append(el("p", {}, el("span", { class: `badge ${ok ? "ok" : "bad"}` }, ok ? "Matches ground truth" : "Does not match ground truth")));
  const det = ev.detection;
  const kv2 = el("dl", { class: "kv" });
  kv2.append(el("dt", {}, "Detection recall"), el("dd", {}, pct(det.recall)));
  kv2.append(el("dt", {}, "Precision"), el("dd", {}, pct(det.precision)));
  kv2.append(el("dt", {}, "ID switches"), el("dd", {}, ev.tracking.id_switches));
  if (ev.congestion.onset_error_seconds !== null && ev.congestion.onset_error_seconds !== undefined) {
    kv2.append(el("dt", {}, "Onset error"), el("dd", {}, `${fmt(ev.congestion.onset_error_seconds)} s`));
  }
  box.append(kv2);
}

function select(data, index) {
  const s = data.scenarios[index];
  document.querySelectorAll(".tab").forEach((t, i) => t.setAttribute("aria-selected", String(i === index)));
  const video = document.getElementById("video");
  video.src = s.video;
  video.poster = s.poster;
  video.setAttribute("aria-label", `${s.title}: annotated rendered video`);
  document.getElementById("note").textContent = s.note;
  finding(s);
  try { localStorage.setItem("scenario", s.name); } catch (e) { /* storage unavailable */ }
}

function tiles(summary) {
  const host = document.getElementById("tiles");
  const t = (num, lab) => el("div", { class: "tile" }, el("div", { class: "num" }, num), el("div", { class: "lab" }, lab));
  host.replaceChildren(
    t(`${summary.outcome_correct}/${summary.scenarios}`, "scenarios with the correct outcome"),
    t(pct(summary.detection_recall), "detection recall (visible subjects)"),
    t(pct(summary.detection_precision), "detection precision"),
    t(summary.id_switches, "track ID switches"),
  );
}

async function main() {
  const data = await (await fetch("data/showcase.json")).json();
  const tabs = document.getElementById("tabs");
  data.scenarios.forEach((s, i) => {
    const b = el("button", { class: "tab", role: "tab", type: "button" }, s.title);
    b.addEventListener("click", () => select(data, i));
    tabs.append(b);
  });
  let start = 0;
  try {
    const saved = localStorage.getItem("scenario");
    const found = data.scenarios.findIndex((s) => s.name === saved);
    if (found >= 0) start = found;
  } catch (e) { /* storage unavailable */ }
  select(data, start);
  tiles(data.summary);
  const list = document.getElementById("credits");
  for (const c of data.credits) {
    const a = el("a", { href: c.source }, c.name);
    list.append(el("li", {}, a, ` by ${c.author} (${c.license}), ${c.kind}`));
  }
}

main().catch((err) => {
  document.getElementById("finding").textContent = `Could not load showcase data: ${err.message}`;
});
