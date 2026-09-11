/* Page behaviour: capture the photos, post them, draw the report.
   No compliance logic here - the verdict and every finding arrive from the
   server already decided. */

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const files = {DECLARATION:null, FRONT:null};


/* ---- capture ---------------------------------------------------------- */

function bindSlot(kind, inputIds, thumbId, slotId, lblId, capId){
  inputIds.forEach(inputId => $(inputId).addEventListener('change', e => {
    const f = e.target.files[0];
    if(!f) return;
    files[kind] = f;
    $(thumbId).src = URL.createObjectURL(f);
    $(slotId).classList.add('filled');
    $(lblId).textContent = 'Retake';
    $(capId).textContent = f.name.length > 28 ? f.name.slice(0,28) + '\u2026' : f.name;
    $('#go').disabled = !files.DECLARATION;
  }));
}

bindSlot('DECLARATION',['#cam-dec','#file-dec'],'#thumb-dec','#slot-dec','#lbl-dec','#cap-dec');
bindSlot('FRONT',['#cam-front','#file-front'],'#thumb-front','#slot-front','#lbl-front','#cap-front');

const show = id => {
  ['#capture','#working','#report'].forEach(s => $(s).classList.add('hide'));
  $(id).classList.remove('hide');
};

function reset(){
  files.DECLARATION = files.FRONT = null;
  ['#cam-dec','#file-dec','#cam-front','#file-front'].forEach(s => $(s).value = '');
  ['#slot-dec','#slot-front'].forEach(s => $(s).classList.remove('filled'));
  $('#thumb-dec').removeAttribute('src'); $('#thumb-front').removeAttribute('src');
  $('#lbl-dec').textContent = 'Take photo'; $('#lbl-front').textContent = 'Take photo';
  $('#cap-dec').textContent = 'The side with the fine print. Required.';
  $('#cap-front').textContent = 'Add it if the price or quantity is on the front.';
  $('#go').disabled = true;
  show('#capture'); $('#history-wrap').classList.remove('hide');
  window.scrollTo(0,0);
}


/* ---- single check ----------------------------------------------------- */

$('#go').addEventListener('click', async () => {
  const fd = new FormData();
  const panels = [];
  if(files.DECLARATION){ fd.append('images', files.DECLARATION); panels.push('DECLARATION'); }
  if(files.FRONT){ fd.append('images', files.FRONT); panels.push('FRONT'); }
  panels.forEach(p => fd.append('panels', p));
  if($('#f-rest').checked) fd.append('restaurant_packed','1');
  if($('#f-drug').checked) fd.append('drug_price_control','1');
  if($('#f-inst').checked) fd.append('institutional','1');

  show('#working');
  $('#history-wrap').classList.add('hide');
  try{
    const {ok, data} = await API.createScan(fd);
    if(!ok){ renderError(data); return; }
    renderReport(data);
    loadHistory();
  }catch(err){
    renderError({detail:'Could not reach the server. Check that the phone and the laptop are on the same network.'});
  }
});


/* ---- bulk check ------------------------------------------------------- */
/* Strictly one at a time. Firing them in parallel would hit the free-tier rate
   limit immediately and most of the batch would come back as 429s. */

$('#file-bulk').addEventListener('change', async e => {
  const picked = Array.from(e.target.files);
  if(!picked.length) return;
  e.target.value = '';

  const rows = picked.map((f,i) => {
    const id = 'q' + Date.now() + i;
    return {id, file:f, name: f.name.length > 30 ? f.name.slice(0,30)+'\u2026' : f.name};
  });
  $('#queue').innerHTML = rows.map(r =>
    `<div id="${r.id}"><span>${esc(r.name)}</span><span class="st q-wait">waiting</span></div>`
  ).join('');

  const setState = (id, cls, text) => {
    const el = document.querySelector('#' + id + ' .st');
    if(el){ el.className = 'st ' + cls; el.textContent = text; }
  };

  for(const r of rows){
    setState(r.id, 'q-run', 'checking\u2026');
    const fd = new FormData();
    fd.append('images', r.file);
    fd.append('panels', 'DECLARATION');
    try{
      const {ok, data} = await API.createScan(fd);
      if(!ok){ setState(r.id, 'q-err', 'failed'); continue; }
      const label = {COMPLIANT:'compliant', NON_COMPLIANT:'not compliant',
                     EXEMPT:'exempt'}[data.verdict] || 'done';
      setState(r.id, data.verdict === 'COMPLIANT' ? 'q-ok' : 'q-err', label);
    }catch(err){
      setState(r.id, 'q-err', 'failed');
    }
    loadHistory();
  }
});


/* ---- report ----------------------------------------------------------- */

const MARK = {PASS:['m-pass','\u2713'], FAIL:['m-fail','\u2715'], SKIP:['m-skip','\u2013'],
              RECHECK:['m-recheck','?'], INFO:['m-info','i']};

function verdictBlock(d){
  if(d.verdict === 'EXEMPT') return `<div class="verdict v-exempt"><h3>Outside the Rules</h3>
    <p>${esc(d.exempt_reason)}</p></div>`;
  const c = d.counts || {};
  if(d.verdict === 'COMPLIANT') return `<div class="verdict v-pass"><h3>Compliant</h3>
    <p>${c.passed} checks passed. No violation found.</p></div>`;
  if(d.verdict === 'INCOMPLETE') return `<div class="verdict v-part"><h3>Check incomplete</h3>
    <p>No violation found in what was visible, but ${c.recheck}
    ${c.recheck === 1 ? 'declaration is' : 'declarations are'} printed on a part of the package
    that was not photographed. Capture that panel and scan again.</p></div>`;
  const bits = [];
  if(c.major) bits.push(c.major + (c.major===1?' violation':' violations'));
  if(c.minor) bits.push(c.minor + (c.minor===1?' formatting defect':' formatting defects'));
  const tail = c.recheck
    ? ` ${c.recheck} further ${c.recheck === 1 ? 'declaration is' : 'declarations are'} on a panel
       that was not photographed.` : '';
  return `<div class="verdict v-fail"><h3>Not compliant</h3>
    <p>${bits.join(' and ')}.${tail}</p></div>`;
}

function findingBlock(v){
  const [cls, glyph] = MARK[v.status] || MARK.SKIP;
  return `<div class="finding">
    <span class="mark ${cls}" aria-hidden="true">${glyph}</span>
    <div class="top"><span class="name">${esc(v.title)}</span>
      <span class="cite">${esc(v.citation)}</span></div>
    <div class="msg">${esc(v.message)}</div>
    ${v.observed ? `<div class="obs">On the label: ${esc(v.observed)}</div>` : ''}
    ${v.status==='FAIL' && v.severity!=='INFO'
      ? `<div class="sev s-${esc(v.severity)}">${v.severity==='MAJOR'
          ? 'Legal violation' : 'Formatting defect'}</div>` : ''}
    ${v.verified === false ? `<div class="unverified">Citation not yet verified against the Gazette text.</div>` : ''}
  </div>`;
}

function fieldsTable(f){
  const rows = Object.entries(f || {}).filter(([,v]) => v);
  if(!rows.length) return '';
  return `<details class="read-fields"><summary>What was read off the label (${rows.length} fields)</summary>
    <table>${rows.map(([k,v]) =>
      `<tr><td>${esc(k.replace(/_/g,' '))}</td><td>${esc(v)}</td></tr>`).join('')}</table>
    </details>`;
}

function renderReport(d){
  show('#report');
  const order = {FAIL:0, RECHECK:1, INFO:2, PASS:3, SKIP:4};
  const vs = (d.violations || []).slice().sort((a,b) => order[a.status] - order[b.status]);
  $('#report').innerHTML = `
    ${verdictBlock(d)}
    <p class="scanned">${esc(d.product_label || 'Unnamed product')} \u00b7 check #${d.id}</p>
    ${vs.map(findingBlock).join('')}
    ${fieldsTable(d.fields_read)}
    ${(d.unclear && d.unclear.length) ? `<p class="hint hint--gap">
      Read with low confidence: ${d.unclear.map(f => esc(f.replace(/_/g,' '))).join(', ')}.
      Retake the photo if a finding above looks wrong.</p>` : ''}
    ${d.notes ? `<p class="hint hint--gap-sm">Reader note: ${esc(d.notes)}</p>` : ''}
    <button class="btn secondary restart" onclick="reset()">Check another package</button>`;
  $('#history-wrap').classList.remove('hide');
  window.scrollTo(0,0);
}

function renderError(data){
  show('#report');
  $('#report').innerHTML = `
    <div class="error"><strong>The label could not be read</strong>
    ${esc(data.detail || 'Unknown error.')}
    ${data.hint ? '<br><br>' + esc(data.hint) : ''}</div>
    <button class="btn secondary restart" onclick="reset()">Try again</button>`;
  $('#history-wrap').classList.remove('hide');
}


/* ---- history ---------------------------------------------------------- */

const TAG = {COMPLIANT:['Compliant','tag-pass'], NON_COMPLIANT:['Not compliant','tag-fail'],
             INCOMPLETE:['Incomplete','tag-part'], EXEMPT:['Exempt','tag-exempt'],
             UNKNOWN:['\u2014','tag-unknown']};

async function loadHistory(){
  try{
    const list = await API.history();
    if(!list.length){
      $('#history').innerHTML = `<p class="hint">Nothing checked yet.</p>`; return;
    }
    $('#history').innerHTML = list.map(s => {
      const [text, cls] = TAG[s.verdict] || TAG.UNKNOWN;
      const c = s.counts || {};
      const detail = s.verdict === 'NON_COMPLIANT'
        ? `${c.major||0} violations, ${c.minor||0} defects` : '';
      return `<button onclick="openScan(${s.id})">
        <span class="row"><span class="name">${esc(s.product_label || 'Unnamed product')}</span>
        <span class="tag ${cls}">${text}</span></span>
        <span class="sub">#${s.id}${detail ? ' \u00b7 ' + detail : ''}${s.is_demo ? ' \u00b7 example' : ''}</span>
      </button>`;
    }).join('');
  }catch(e){ $('#history').innerHTML = `<p class="hint">History unavailable.</p>`; }
}

async function openScan(id){
  show('#working');
  try{
    renderReport(await API.scan(id));
  }catch(e){ renderError({detail:'Could not load that check.'}); }
}

loadHistory();