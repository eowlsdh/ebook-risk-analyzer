(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("report-data").textContent);
  const text = (value) => String(value ?? "");
  const element = (tag, value, className) => { const node = document.createElement(tag); node.textContent = text(value); if (className) node.className = className; return node; };
  const overview = document.getElementById("overview");
  const book = data.book || {};
  if (data.summary?.disclaimer) document.getElementById("disclaimer").textContent = data.summary.disclaimer;
  [["검토 신호", (data.findings || []).length], ["종합 검토 점수", data.summary?.overall_score ?? "-"], ["검토 우선순위", data.summary?.risk_level ?? "-"], ["장", book.chapter_count ?? 0], ["자료", book.resource_count ?? 0]].forEach(([label, value]) => { const card = document.createElement("div"); card.className = "card"; card.append(element("div", value, "metric"), element("div", label)); overview.append(card); });
  const scores = document.getElementById("scores");
  Object.entries(data.category_scores || {}).forEach(([category, score]) => { const item = document.createElement("div"); item.className = "score"; item.append(element("span", category), element("strong", `${Number(score).toFixed(1)} / 100`)); const bar = document.createElement("div"); bar.className = "bar"; const fill = document.createElement("span"); fill.style.width = `${Math.max(0, Math.min(100, Number(score) || 0))}%`; bar.append(fill); item.append(bar); scores.append(item); });
  const list = (id, values) => Object.entries(values || {}).forEach(([name, count]) => document.getElementById(id).append(element("li", `${name}: ${count}건`)));
  list("severity-summary", data.severity_counts); list("chapter-summary", data.chapter_counts);
  const category = document.getElementById("category-filter"), severity = document.getElementById("severity-filter"), query = document.getElementById("text-filter");
  const options = (select, values) => Object.keys(values || {}).forEach(value => { const option = document.createElement("option"); option.value = value; option.textContent = value; select.append(option); });
  options(category, data.category_counts); options(severity, data.severity_counts);
  const findings = document.getElementById("findings"), count = document.getElementById("result-count");
  function render() { const needle = query.value.trim().toLocaleLowerCase(); const shown = (data.findings || []).filter(f => { const location = f.location || {}; return (!category.value || f.category === category.value) && (!severity.value || f.severity === severity.value) && (!needle || [f.excerpt, f.reason, f.review_action, location.chapter, location.file].some(v => text(v).toLocaleLowerCase().includes(needle))); }); findings.replaceChildren(); shown.forEach(f => { const card = document.createElement("article"); card.className = `finding ${text(f.severity).toLowerCase()}`; const location = f.location || {}; card.append(element("h3", `${f.category} · ${f.severity}`), element("p", `${location.chapter || location.file || "위치 정보 없음"} / 문단 ${location.paragraph ?? "-"}, 문장 ${location.sentence ?? "-"}`, "location")); [["발췌", f.excerpt], ["검토 이유", f.reason], ["권장 검토 조치", f.review_action]].forEach(([label, value]) => { const details = document.createElement("details"); const summary = element("summary", label); const content = element(label === "발췌" ? "blockquote" : "p", value); details.append(summary, content); card.append(details); }); findings.append(card); }); count.textContent = `${shown.length}건의 검토 신호 표시`; }
  [category, severity, query].forEach(control => control.addEventListener("input", render)); render();
  document.getElementById("download-json").addEventListener("click", () => { const blob = new Blob([JSON.stringify({book:data.book,summary:data.summary,category_scores:data.category_scores,findings:data.findings}, null, 2)], {type:"application/json"}); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "report.json"; link.click(); URL.revokeObjectURL(link.href); });
})();
