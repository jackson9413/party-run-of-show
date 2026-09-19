const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let lastSessionId = null;

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function fmtTime(min) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function fmtWhen(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function renderScore(score, verdict) {
  const num = Math.round(score);
  $("#scoreNum").textContent = num;
  $("#scoreVerdict").textContent = verdict;
  const circumference = 2 * Math.PI * 52;
  const offset = circumference - (num / 100) * circumference;
  $("#scoreArc").setAttribute("stroke-dashoffset", offset);
  const colors = ["#e74c3c", "#e67e22", "#f1c40f", "#74b9ff", "#6c5ce7"];
  $("#scoreArc").setAttribute("stroke", colors[Math.min(4, Math.floor(num / 25))]);
}

function renderAxisBars(scoring) {
  const container = $("#axisBars");
  container.innerHTML = "";
  for (const [k, v] of Object.entries(scoring.axes)) {
    const w = Math.round(scoring.weights[k] * 100);
    const row = document.createElement("div");
    row.className = "axis";
    row.innerHTML = `
      <span class="axis-name">${k.replace(/_/g, " ")} <small style="color:#b2bec3">(${w}%)</small></span>
      <span class="axis-bar"><span class="axis-bar-fill" style="width: ${v}%"></span></span>
      <span class="axis-val">${v}</span>
    `;
    container.appendChild(row);
  }
}

function renderTimeline(timeline) {
  const ol = $("#timeline");
  ol.innerHTML = "";
  for (const b of timeline) {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="stage">${b.stage_label}</span>
      <span class="time">${fmtTime(b.start_offset)}<br>→ ${fmtTime(b.end_offset)}</span>
      <span class="body">
        <span class="title">${b.title}
          <span class="energy-pill energy-${b.energy_label}">${b.energy_label}</span>
          ${b.materials && b.materials.length ? `<small style="color:#b2bec3"> · ${b.materials.join(", ")}</small>` : ""}
        </span>
        <p class="meta">${b.rationale}</p>
      </span>
    `;
    ol.appendChild(li);
  }
}

function renderList(sel, items) {
  const ul = $(sel);
  ul.innerHTML = "";
  for (const x of items) {
    const li = document.createElement("li");
    li.textContent = x;
    ul.appendChild(li);
  }
}

async function runBuild() {
  const payload = {
    brief: $("#brief").value,
    occasion: $("#occasion").value,
    group_size: $("#group_size").value ? Number($("#group_size").value) : null,
    total_minutes: $("#total_minutes").value ? Number($("#total_minutes").value) : null,
    energy_target: $("#energy_target").value || null,
    ages: $("#ages").value || null,
    conflict_safe: $("#conflict_safe").checked,
  };
  try {
    const r = await postJSON("/api/generate", payload);
    $("#result").classList.remove("hidden");
    $("#templateLabel").textContent = r.template + " — Run-of-Show";
    $("#metaLine").textContent =
      `${r.actual_minutes} min total · ${r.block_count} blocks · ${r.input.group_size} guests · ${r.input.ages}`;
    renderScore(r.scoring.overall, r.verdict);
    renderAxisBars(r.scoring);
    renderTimeline(r.timeline);
    renderList("#insights", r.insights);
    if (r.flags.length) {
      $("#flagsCard").classList.remove("hidden");
      renderList("#flags", r.flags);
    } else {
      $("#flagsCard").classList.add("hidden");
    }
    // Get latest session id from history
    const hist = await getJSON("/api/sessions");
    if (hist.length) {
      lastSessionId = hist[0].id;
      $("#exportMd").href = `/api/export/${lastSessionId}.md`;
      $("#exportJson").href = `/api/export/${lastSessionId}.json`;
    }
    renderHistory();
  } catch (e) {
    alert("Failed: " + e.message);
  }
}

async function rateRun() {
  if (!lastSessionId) return alert("Build a run-of-show first.");
  const rating = Number($("#rating").value);
  if (!rating || rating < 1 || rating > 5) return alert("Rating 1-5.");
  const notes = $("#notes").value;
  await postJSON("/api/rate", { session_id: lastSessionId, rating, notes });
  alert("Saved ⭐ " + rating);
  renderHistory();
}

function renderHistory() {
  getJSON("/api/sessions").then((rows) => {
    const ul = $("#history");
    ul.innerHTML = "";
    if (!rows.length) {
      ul.innerHTML = '<li><span class="brief">No runs yet.</span></li>';
      return;
    }
    for (const r of rows) {
      const li = document.createElement("li");
      const stars = r.rating ? "★".repeat(r.rating) + "☆".repeat(5 - r.rating) : "";
      li.innerHTML = `
        <span class="when">${fmtWhen(r.created_at)}</span>
        <span class="brief">${r.occasion} · ${(r.brief || "").slice(0, 80)}${(r.brief || "").length > 80 ? "…" : ""}</span>
        <span class="rating-stars">${stars}</span>
        <a href="/api/export/${r.id}.md" target="_blank">md</a>
      `;
      ul.appendChild(li);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("#runBtn").addEventListener("click", runBuild);
  $("#saveBtn").addEventListener("click", rateRun);
  renderHistory();
});
