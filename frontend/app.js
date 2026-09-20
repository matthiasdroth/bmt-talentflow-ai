const $ = (id) => document.getElementById(id);
let uploadedDocument = null;

function cleanExtractedText(text) {
  const decoder = document.createElement('textarea');
  decoder.innerHTML = text || '';
  return decoder.value
    .replace(/\\(?=[^A-Za-z0-9\s])/g, '')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+/g, ' ')
    .replace(/ *\n */g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
}

function renderDocuments(documents, filename) {
  const container = $('documents');
  if (!documents?.length) {
    container.classList.add('hidden');
    return;
  }
  container.classList.remove('hidden');
  container.innerHTML = `<div class="documents-title"><strong>Erkannte Dokumente</strong><span>${escapeHtml(filename || 'Bewerbungsunterlagen')} · ${documents.length} Bereiche</span></div>${documents.map((document, index) => `<details class="document-card" ${index === 0 ? 'open' : ''}><summary><span class="document-type">${escapeHtml(document.type)}</span><span class="document-chevron" aria-hidden="true"></span></summary><pre>${escapeHtml(cleanExtractedText(document.text))}</pre></details>`).join('')}`;
}

function updateCandidateIdentity(name) {
  if (!name) return;
  const cleanName = name.replace(/^Dr\.\s+/i, '').trim();
  const initials = cleanName.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0].toUpperCase()).join('');
  $('candidate-name').textContent = name;
  $('candidate-title').textContent = name;
  const avatar = document.querySelector('.avatar');
  if (avatar) avatar.textContent = initials;
  $('candidate-headline').textContent = 'Bewerbungsunterlagen hochgeladen';
  $('candidate-summary').textContent = `${name} · Dokumente wurden erfolgreich eingelesen.`;
}

async function loadData() {
  const [job, candidate] = await Promise.all([
    fetch('/api/job').then(r => r.json()),
    fetch('/api/candidate').then(r => r.json())
  ]);
  $('job-title').textContent = job.title;
  $('candidate-name').textContent = candidate.name;
  $('candidate-headline').textContent = candidate.headline;
  $('candidate-title').textContent = candidate.name;
  $('candidate-summary').textContent = candidate.summary;
}

function renderResult(data) {
  $('result').classList.remove('hidden');
  $('result').innerHTML = `<div class="score-row"><div class="score">${data.score}<small>/100</small></div><div><div class="recommendation">${data.recommendation}</div><div class="evidence">Konfidenz ${(data.confidence * 100).toFixed(0)}% · Analyse abgeschlossen</div></div></div><div class="grid"><div class="panel"><h3>ANFORDERUNGS-MATCH</h3>${data.matched.map(item => `<div class="match"><div class="match-top"><span>${item.requirement}</span><strong>${item.score}%</strong></div><div class="bar"><i style="width:${item.score}%"></i></div><div class="evidence">${item.evidence}</div></div>`).join('')}</div><div><div class="panel"><h3>OFFENER PUNKT</h3>${data.gaps.map(gap => `<div class="gap">${gap}</div>`).join('')}</div><div class="panel" style="margin-top:22px"><h3>VORGESCHLAGENE INTERVIEWFRAGEN</h3>${data.questions.map(q => `<div class="question">${q}</div>`).join('')}</div></div></div><div class="audit">Audit: ${data.audit.source} · ${data.audit.model} · Prompt ${data.audit.prompt_version} · Keine automatische Einstellungsentscheidung</div>`;
}

$('analyze').addEventListener('click', async () => {
  $('analyze').disabled = true;
  $('analyze').innerHTML = 'Analyse läuft …';
  const result = await fetch('/api/analyze', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({document_text: uploadedDocument?.text || ''})
  }).then(r => r.json());
  renderResult(result);
  $('analyze').innerHTML = 'Erneut analysieren <span>↻</span>';
  $('analyze').disabled = false;
});

$('resume').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const status = $('upload-status');
  status.classList.remove('hidden', 'error', 'success');
  status.textContent = `${file.name} wird gelesen …`;
  const form = new FormData();
  form.append('file', file);
  try {
    const response = await fetch('/api/candidate/upload', {method: 'POST', body: form});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Upload fehlgeschlagen.');
    const cleanedText = cleanExtractedText(data.text || data.preview);
    uploadedDocument = {...data, text: cleanedText, documents: data.documents?.map(document => ({...document, text: cleanExtractedText(document.text)}))};
    updateCandidateIdentity(data.candidate_name);
    status.classList.add('success');
    status.textContent = data.message;
    renderDocuments(uploadedDocument.documents, data.filename);
  } catch (error) {
    status.classList.add('error');
    status.textContent = error.message;
    $('extracted').classList.add('hidden');
  }
});

loadData();
