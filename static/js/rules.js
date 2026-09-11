/* The rules screen. Reads the same catalogue the engine runs, so this page
   cannot drift from what the checks actually do. */

const list = document.querySelector('#rules-list');
const escape = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const CONSEQUENCE = {
  MAJOR: 'Failing this is a legal violation',
  MINOR: 'Failing this is a formatting defect',
  INFO:  'Reported for information, not a compliance claim',
};

function ruleCard(rule){
  const consequence = CONSEQUENCE[rule.severity] || '';
  return `<article class="rule">
    <div class="rule__top">
      <span class="rule__code">${escape(rule.code)}</span>
      <span class="cite">${escape(rule.citation)}</span>
    </div>
    <h2 class="rule__title">${escape(rule.title)}</h2>
    <p class="rule__req">${escape(rule.requirement)}</p>
    <p class="rule__foot ${rule.severity === 'MAJOR' ? 'is-major' : ''}">${escape(consequence)}</p>
    ${rule.verified === false
      ? `<p class="unverified">Citation not yet verified against the Gazette text.</p>` : ''}
  </article>`;
}

(async function load(){
  try{
    const rules = await API.rules();
    if(!rules.length){
      list.innerHTML = `<p class="tip">No rules are loaded. Run <code>manage.py seed_rules</code>.</p>`;
      return;
    }
    list.innerHTML = `<p class="rules__count">${rules.length} checks run on every label</p>`
      + rules.map(ruleCard).join('');
  }catch(err){
    list.innerHTML = `<p class="tip">The catalogue could not be loaded.</p>`;
  }
})();