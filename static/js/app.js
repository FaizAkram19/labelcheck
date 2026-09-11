/* Page behaviour: capture the photos, post them, draw the report.
   No compliance logic here - the verdict and every finding arrive from the
   server already decided. */

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const files = {DECLARATION:null, FRONT:null};

/* Filled in from /api/health/ so the waiting screen can name a real number
   instead of a vague promise. Never blocks anything if it fails. */
let ruleCount = null;
API.health().then(h => { ruleCount = h.rules_loaded; }).catch(() => {});


/* ---- capture ---------------------------------------------------------- */

function bindSlot(kind, inputIds, thumbId, phId, slotId, lblId, capId){
  inputIds.forEach(inputId => $(inputId).addEventListener('change', e => {
    const f = e.target.files[0];
    if(!f) return;
    files[kind] = f;
    const thumb = $(thumbId);
    thumb.src = URL.createObjectURL(f);
    thumb.hidden = false;
    $(phId).hidden = true;
    $(slotId).classList.add('filled');
    $(lblId).textContent = 'Retake';
    $(capId).textContent = f.name.length > 26 ? f.name.slice(0,26) + '\u2026' : f.name;
    $('#go').disabled = !files.DECLARATION;
  }));
}

bindSlot('DECLARATION',['#cam-dec','#file-dec'],'#thumb-dec','#ph-dec','#slot-dec','#lbl-dec','#cap-dec');
bindSlot('FRONT',['#cam-front','#file-front'],'#thumb-front','#ph-front','#slot-front','#lbl-front','#cap-front');

const show = id => {
  ['#capture','#working','#report'].forEach(s => $(s).classList.add('hide'));
  $(id).classList.remove('hide');
};

function reset(){
  files.DECLARATION = files.FRONT = null;
  ['#cam-dec','#file-dec','#cam-front','#file-front'].forEach(s => $(s).value = '');
  ['#slot-dec','#slot-front'].forEach(s => $(s).classList.remove('filled'));
  ['#thumb-dec','#thumb-front'].forEach(s => {
    $(s).removeAttribute('src'); $(s).hidden = true;
  });
  ['#ph-dec','#ph-front'].forEach(s => { $(s).hidden = false; });
  $('#lbl-dec').textContent = 'Take photo'; $('#lbl-front').textContent = 'Take photo';
  $('#cap-dec').textContent = 'The side with the fine print. Required.';
  $('#cap-front').textContent = 'Add it if the price or quantity is on the front.';
  $('#go').disabled = true;
  show('#capture'); $('#history-wrap').classList.remove('hide');
  window.scrollTo(0,0);
}


/* ---- the wait --------------------------------------------------------- */
/* A scan takes several seconds and almost all of it is the vision model. One
   frozen line of text for that long reads as a hang, so the stages name what is
   happening - which is also the pipeline we want a judge to notice. */

function startStages(){
  const stages = [
    [0,    'Uploading the photos'],
    [1400, 'Reading the declarations off the label'],
    [4000, ruleCount ? `Checking ${ruleCount} rules` : 'Checking against the Rules'],
  ];
  const timers = stages.map(([delay, text]) =>
    setTimeout(() => { $('#stage').textContent = text; }, delay));
  return () => timers.forEach(clearTimeout);
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
  const stopStages = startStages();
  try{
    const {ok, data} = await API.createScan(fd);
    if(!ok){ renderError(data); return; }
    renderReport(data);
    loadHistory();
  }catch(err){
    renderError({detail:'Could not reach the server. Check that the phone and the laptop are on the same network.'});
  }finally{
    stopStages();
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
    return {id, file:f, name: f.name.length > 28 ? f.name.slice(0,28)+'\u2026' : f.name};
  });
  $('#queue').innerHTML = rows.map(r =>
    `<div class="queue__row" id="${r.id}"><span class="queue__name">${esc(r.name)}</span>
     <span class="st q-wait">waiting</span></div>`
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
                     INCOMPLETE:'incomplete', EXEMPT:'exempt'}[data.verdict] || 'done';
      setState(r.id, data.verdict === 'COMPLIANT' ? 'q-ok' : 'q-err', label);
      const row = document.getElementById(r.id);
      if(row){
        row.classList.add('queue__row--open');
        row.addEventListener('click', () => openScan(data.id));
      }
    }catch(err){
      setState(r.id, 'q-err', 'failed');
    }
    loadHistory();
  }
});


/* ---- report ----------------------------------------------------------- */

const MARK = {PASS:['m-pass','\u2713'], FAIL:['m-fail','\u2715'], SKIP:['m-skip','\u2013'],
              RECHECK:['m-recheck','?'], INFO:['m-info','i']};

const PANEL_NAME = {DECLARATION:'Declaration panel', FRONT:'Front panel'};

function verdictBlock(d){
  if(d.verdict === 'EXEMPT') return `<div class="verdict v-exempt"><h2>Outside the Rules</h2>
    <p>${esc(d.exempt_reason)}</p></div>`;
  const c = d.counts || {};
  if(d.verdict === 'COMPLIANT') return `<div class="verdict v-pass"><h2>Compliant</h2>
    <p>${c.passed} checks passed. No violation found.</p></div>`;
  if(d.verdict === 'INCOMPLETE') return `<div class="verdict v-part"><h2>Check incomplete</h2>
    <p>No violation found in what was visible, but ${c.recheck}
    ${c.recheck === 1 ? 'declaration is' : 'declarations are'} printed on a part of the package
    that was not photographed. Capture that panel and scan again.</p></div>`;
  const bits = [];
  if(c.major) bits.push(c.major + (c.major===1?' violation':' violations'));
  if(c.minor) bits.push(c.minor + (c.minor===1?' formatting defect':' formatting defects'));
  const tail = c.recheck
    ? ` ${c.recheck} further ${c.recheck === 1 ? 'declaration is' : 'declarations are'} on a panel
       that was not photographed.` : '';
  return `<div class="verdict v-fail"><h2>Not compliant</h2>
    <p>${bits.join(' and ')}.${tail}</p></div>`;
}

/* The photographs the verdict was read from. Without these a report is a claim
   about a packet nobody can see. */
function shotsStrip(images){
  const shots = (images || []).filter(i => i.url);
  if(!shots.length) return '';
  return `<div class="shots">${shots.map(i => `
    <a class="shots__item" href="${esc(i.url)}" target="_blank" rel="noopener">
      <img src="${esc(i.url)}" alt="${esc(PANEL_NAME[i.panel] || 'Label photo')}">
      <span>${esc(PANEL_NAME[i.panel] || 'Label photo')}</span>
    </a>`).join('')}</div>`;
}

/* Title gets the full width. The citation sits in the footer with the severity,
   where a long one like "Rule 5 and Second Schedule" cannot squeeze it. */
function findingBlock(v){
  const [cls, glyph] = MARK[v.status] || MARK.SKIP;
  const severity = v.status === 'FAIL' && v.severity !== 'INFO'
    ? `<span class="sev s-${esc(v.severity)}">${v.severity === 'MAJOR'
        ? 'Legal violation' : 'Formatting defect'}</span>` : '';
  return `<div class="finding">
    <span class="mark ${cls}" aria-hidden="true">${glyph}</span>
    <span class="name">${esc(v.title)}</span>
    <div class="msg">${esc(v.message)}</div>
    ${v.observed ? `<div class="obs">On the label: ${esc(v.observed)}</div>` : ''}
    <div class="foot">
      <span class="cite">${esc(v.citation)}</span>
      ${severity}
      ${v.verified === false ? `<span class="unverified">Citation unverified</span>` : ''}
    </div>
  </div>`;
}

/* Passes and non-applicable checks fold away. A judge should meet the verdict,
   then the breaches - not scroll eleven green ticks to find the one red cross.
   The count stays visible so the thoroughness is still on show. */
function quietBlock(quiet, openByDefault){
  if(!quiet.length) return '';
  const passed = quiet.filter(v => v.status === 'PASS').length;
  const skipped = quiet.length - passed;
  const bits = [];
  if(passed) bits.push(`${passed} ${passed === 1 ? 'check' : 'checks'} passed`);
  if(skipped) bits.push(`${skipped} not applicable`);
  return `<details class="disclose" ${openByDefault ? 'open' : ''}>
    <summary>${bits.join(', ')}</summary>
    <div class="findings findings--quiet">${quiet.map(findingBlock).join('')}</div>
  </details>`;
}

function fieldsTable(f){
  const rows = Object.entries(f || {}).filter(([,v]) => v);
  if(!rows.length) return '';
  return `<details class="disclose read-fields">
    <summary>What was read off the label (${rows.length} fields)</summary>
    <table>${rows.map(([k,v]) =>
      `<tr><td>${esc(k.replace(/_/g,' '))}</td><td>${esc(v)}</td></tr>`).join('')}</table>
    </details>`;
}

function renderReport(d){
  show('#report');
  const order = {FAIL:0, RECHECK:1, INFO:2, PASS:3, SKIP:4};
  const vs = (d.violations || []).slice().sort((a,b) => order[a.status] - order[b.status]);
  const loud = vs.filter(v => v.status === 'FAIL' || v.status === 'RECHECK' || v.status === 'INFO');
  const quiet = vs.filter(v => v.status === 'PASS' || v.status === 'SKIP');
  /* Nothing to answer for, so the passes open on their own - the thoroughness
     is the point of a clean report. */
  const clean = !vs.some(v => v.status === 'FAIL' || v.status === 'RECHECK');
  $('#report').innerHTML = `
    ${verdictBlock(d)}
    <p class="scanned">${esc(d.product_label || 'Unnamed product')} \u00b7 check #${d.id}</p>
    ${shotsStrip(d.images)}
    ${loud.length ? `<div class="findings">${loud.map(findingBlock).join('')}</div>` : ''}
    ${quietBlock(quiet, clean)}
    ${fieldsTable(d.fields_read)}
    ${(d.unclear && d.unclear.length) ? `<p class="tip tip--gap">
      Read with low confidence: ${d.unclear.map(f => esc(f.replace(/_/g,' '))).join(', ')}.
      Retake the photo if a finding above looks wrong.</p>` : ''}
    ${d.notes ? `<p class="tip">Reader note: ${esc(d.notes)}</p>` : ''}
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

const TAG = {COMPLIANT:['Compliant','pill-pass'], NON_COMPLIANT:['Not compliant','pill-fail'],
             INCOMPLETE:['Incomplete','pill-part'], EXEMPT:['Exempt','pill-exempt'],
             UNKNOWN:['Unknown','pill-unknown']};

function when(iso){
  const d = new Date(iso);
  if(isNaN(d)) return '';
  return d.toLocaleString('en-IN',
    {day:'numeric', month:'short', hour:'numeric', minute:'2-digit'});
}

async function loadHistory(){
  try{
    const list = await API.history();
    if(!list.length){
      $('#history').innerHTML =
        `<p class="empty">Nothing checked yet. Photograph a label to start.</p>`;
      return;
    }
    $('#history').innerHTML = list.map(s => {
      const [text, cls] = TAG[s.verdict] || TAG.UNKNOWN;
      const c = s.counts || {};
      const detail = s.verdict === 'NON_COMPLIANT'
        ? `${c.major||0} violations, ${c.minor||0} defects` : '';
      const sub = [when(s.created_at), detail, s.is_demo ? 'example' : '']
        .filter(Boolean).join(' \u00b7 ');
      return `<button onclick="openScan(${s.id})">
        <span class="row"><span class="name">${esc(s.product_label || 'Unnamed product')}</span>
        <span class="pill ${cls}">${text}</span></span>
        <span class="sub">${esc(sub)}</span>
      </button>`;
    }).join('');
  }catch(e){
    $('#history').innerHTML = `<p class="empty">History unavailable.</p>`;
  }
}

async function openScan(id){
  show('#working');
  $('#stage').textContent = 'Opening the check';
  try{
    renderReport(await API.scan(id));
  }catch(e){ renderError({detail:'Could not load that check.'}); }
}

loadHistory();