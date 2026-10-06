/* Date-of-birth field: type it (DD/MM/YYYY, digits only, slashes added
 * automatically) or pick it from the calendar button. Typing is much faster
 * than scrolling a date picker back several decades on a phone.
 *
 * Usage: <input id="dob" data-dob> ... then dobISO(element) returns
 * "YYYY-MM-DD", or "" when the field is empty or not a real past date.
 */
(function () {
  const css = `.dob-wrap{position:relative;display:block}
.dob-wrap input.dob-text{padding-right:48px}
.dob-wrap .dob-cal{position:absolute;top:0;right:0;height:100%;width:44px;border:none;background:none;cursor:pointer;
  font-size:18px;line-height:1;color:inherit;opacity:.75;padding:0}
.dob-wrap .dob-cal:hover{opacity:1}
.dob-wrap input.dob-native{position:absolute;right:0;bottom:0;width:1px;height:1px;opacity:0;pointer-events:none;border:0;padding:0}
.dob-wrap.invalid input.dob-text{border-color:#b3261e}`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  const pad = n => String(n).padStart(2, '0');

  function parse(text) {
    const s = String(text || '').trim();
    if (!s) return '';
    let d, m, y;
    let hit = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);                  // ISO (autofill)
    if (hit) { y = +hit[1]; m = +hit[2]; d = +hit[3]; }
    else {
      hit = s.match(/^(\d{1,2})[\/.\-\s](\d{1,2})[\/.\-\s](\d{4})$/);       // 5/3/1975, 05.03.1975
      if (!hit) hit = s.replace(/\D/g, '').match(/^(\d{2})(\d{2})(\d{4})$/); // 05031975
      if (!hit) return null;
      d = +hit[1]; m = +hit[2]; y = +hit[3];
    }
    const date = new Date(Date.UTC(y, m - 1, d));
    if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return null;
    if (y < 1900 || date > new Date()) return null;
    return `${y}-${pad(m)}-${pad(d)}`;
  }

  function show(input, iso) {
    const [y, m, d] = iso.split('-');
    input.value = `${d}/${m}/${y}`;
  }

  function validate(input) {
    const iso = parse(input.value);
    input.closest('.dob-wrap').classList.toggle('invalid', iso === null);
    return iso;
  }

  function enhance(input) {
    if (input.dataset.dobReady) return;
    input.dataset.dobReady = '1';
    input.type = 'text';
    input.inputMode = 'numeric';
    input.maxLength = 10;
    input.placeholder = 'DD/MM/YYYY';
    input.autocomplete = 'bday';
    input.classList.add('dob-text');

    const wrap = document.createElement('span');
    wrap.className = 'dob-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const native = document.createElement('input');
    native.type = 'date';
    native.className = 'dob-native';
    native.tabIndex = -1;
    native.setAttribute('aria-hidden', 'true');
    native.max = new Date().toISOString().slice(0, 10);
    native.min = '1900-01-01';
    wrap.appendChild(native);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dob-cal';
    btn.textContent = '📅';
    btn.setAttribute('aria-label', 'Choose date from calendar');
    wrap.appendChild(btn);

    btn.addEventListener('click', () => {
      const iso = parse(input.value);
      native.value = iso || '1980-01-01';
      try { native.showPicker(); } catch (e) { native.focus(); native.click(); }
    });
    native.addEventListener('change', () => {
      if (native.value) { show(input, native.value); validate(input); }
    });

    // Digits only, slashes added as you type: 05031975 -> 05/03/1975.
    input.addEventListener('input', e => {
      const raw = input.value;
      if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) { show(input, raw); return; }   // autofill in ISO
      const deleting = e.inputType && e.inputType.startsWith('delete');
      const digits = raw.replace(/\D/g, '').slice(0, 8);
      let out = digits.slice(0, 2);
      if (digits.length > 2 || (!deleting && digits.length === 2)) out += '/' + digits.slice(2, 4);
      if (digits.length > 4 || (!deleting && digits.length === 4)) out += '/' + digits.slice(4, 8);
      if (deleting && out.endsWith('/')) out = out.slice(0, -1);
      input.value = out;
      input.closest('.dob-wrap').classList.remove('invalid');
    });
    input.addEventListener('blur', () => { if (input.value) validate(input); });
  }

  window.dobISO = function (input) {
    if (!input) return '';
    const iso = validate(input);
    return iso || '';
  };
  window.dobSet = function (input, iso) { if (input && /^\d{4}-\d{2}-\d{2}$/.test(iso || '')) show(input, iso); };
  window.dobParse = parse;

  function init() { document.querySelectorAll('input[data-dob]').forEach(enhance); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
