(() => {
  'use strict';
  const byId = (id) => document.getElementById(id);
  const text = (value) => String(value == null ? '' : value);

  const form = byId('analysis-form');
  if (form) {
    const input = byId('files');
    const directory = byId('directory-files');
    const dropZone = byId('drop-zone');
    const status = byId('file-status');
    const submit = byId('submit-analysis');
    const progress = byId('progress');
    const relativePaths = byId('relative-paths');
    const showFiles = (files) => {
      const items = Array.from(files || []);
      status.textContent = items.length ? `${items.length}개 파일 선택됨: ${items.slice(0, 3).map((file) => file.webkitRelativePath || file.name).join(', ')}${items.length > 3 ? ' …' : ''}` : '아직 선택한 파일이 없습니다.';
    };
    const setFiles = (files, preservePaths = false) => {
      const selected = Array.from(files);
      try {
        const transfer = new DataTransfer();
        selected.forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
      } catch (_) { /* Browser keeps the native picker selection when assignment is unavailable. */ }
      relativePaths.value = preservePaths ? JSON.stringify(selected.map((file) => file.webkitRelativePath || file.name)) : '';
      showFiles(selected);
    };
    input.addEventListener('change', () => { relativePaths.value = ''; showFiles(input.files); });
    directory.addEventListener('change', () => setFiles(directory.files, true));
    byId('choose-files').addEventListener('click', () => input.click());
    byId('choose-directory').addEventListener('click', () => directory.click());
    ['dragenter', 'dragover'].forEach((event) => dropZone.addEventListener(event, (e) => { e.preventDefault(); dropZone.classList.add('dragging'); }));
    ['dragleave', 'drop'].forEach((event) => dropZone.addEventListener(event, (e) => { e.preventDefault(); dropZone.classList.remove('dragging'); }));
    dropZone.addEventListener('drop', (event) => { if (event.dataTransfer && event.dataTransfer.files.length) setFiles(event.dataTransfer.files); });
    dropZone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
    dropZone.addEventListener('click', (event) => { if (event.target === dropZone) input.click(); });
    form.addEventListener('submit', (event) => {
      if (!input.files.length) { event.preventDefault(); status.textContent = '분석할 파일을 하나 이상 선택하세요.'; input.focus(); return; }
      submit.disabled = true;
      progress.hidden = false;
      progress.textContent = '분석 중입니다. 파일 수와 크기에 따라 잠시 걸릴 수 있습니다.';
    });
    return;
  }

  const reportElement = byId('report-data');
  const findingsRoot = byId('findings');
  if (!reportElement || !findingsRoot) return;
  let report;
  try { report = JSON.parse(reportElement.textContent || '{}'); } catch (_) { return; }
  const findings = Array.isArray(report.findings) ? report.findings : [];
  const category = byId('category-filter');
  const severity = byId('severity-filter');
  const chapter = byId('chapter-filter');
  const count = byId('result-count');
  const empty = byId('empty-results');
  const values = (key) => [...new Set(findings.map((item) => text(item[key] || (key === 'chapter' ? item.file : '')).trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ko'));
  const options = (element, items) => items.forEach((item) => { const option = document.createElement('option'); option.value = item; option.textContent = item; element.append(option); });
  options(category, values('category'));
  options(severity, values('severity'));
  options(chapter, values('chapter'));
  const field = (label, value, className) => {
    const wrapper = document.createElement('div');
    const title = document.createElement('dt'); title.textContent = label;
    const content = document.createElement('dd'); content.textContent = text(value) || '정보 없음';
    if (className) content.className = className;
    wrapper.append(title, content);
    return wrapper;
  };
  const render = () => {
    const selected = findings.filter((item) => (!category.value || item.category === category.value) && (!severity.value || item.severity === severity.value) && (!chapter.value || text(item.chapter || item.file) === chapter.value));
    findingsRoot.replaceChildren();
    selected.forEach((item, index) => {
      const level = text(item.severity).toLowerCase().replace(/[^a-z-]/g, '');
      const article = document.createElement('article'); article.className = `finding severity-${level || 'unknown'}`;
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `${text(item.category) || '기타'} · ${text(item.chapter || item.file) || '위치 정보 없음'} (${index + 1})`;
      const badges = document.createElement('div'); badges.className = 'badges';
      [item.severity, item.category].filter(Boolean).forEach((itemText) => { const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = text(itemText); badges.append(badge); });
      const list = document.createElement('dl');
      list.append(field('위치', `${text(item.chapter || item.file)} / 문단 ${text(item.paragraph)} / 문장 ${text(item.sentence)}`));
      list.append(field('원문 발췌', item.excerpt, 'excerpt'));
      list.append(field('검토 이유', item.reason));
      list.append(field('권장 조치', item.review_action));
      details.append(summary, badges, list); article.append(details); findingsRoot.append(article);
    });
    count.textContent = `총 ${findings.length}개 중 ${selected.length}개 표시`;
    empty.hidden = selected.length !== 0;
  };
  [category, severity, chapter].forEach((element) => element.addEventListener('change', render));
  render();
})();
