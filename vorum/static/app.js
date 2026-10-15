(() => {
  const root = document.documentElement;
  let mode = 'auto';
  try { mode = localStorage.getItem('vorum-theme') || 'auto'; } catch (_) {}
  const label = document.querySelector('#theme-label');
  function applyTheme() {
    if (mode === 'auto') delete root.dataset.theme;
    else root.dataset.theme = mode;
    if (label) label.textContent = ({ auto: 'Auto', light: document.documentElement.lang === 'de' ? 'Hell' : 'Light', dark: document.documentElement.lang === 'de' ? 'Dunkel' : 'Dark' })[mode];
  }
  if (!['auto', 'light', 'dark'].includes(mode)) mode = 'auto';
  applyTheme();
  document.querySelector('#theme-toggle')?.addEventListener('click', () => {
    const systemMode = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    const oppositeMode = systemMode === 'dark' ? 'light' : 'dark';
    mode = mode === 'auto' ? oppositeMode : mode === oppositeMode ? systemMode : 'auto';
    try { localStorage.setItem('vorum-theme', mode); } catch (_) {}
    applyTheme();
  });
  document.querySelectorAll('[data-confirm]').forEach(element => {
    element.addEventListener(element.tagName === 'FORM' ? 'submit' : 'click', event => {
      if (!confirm(document.body.dataset.confirmMessage)) event.preventDefault();
    });
  });
  const textarea = document.querySelector('#body');
  const editor = document.querySelector('#rich-editor');
  if (textarea && editor) {
    // Server sanitization remains authoritative; parse the fallback input defensively too.
    const doc = new DOMParser().parseFromString(textarea.value, 'text/html');
    const allowed = new Set(['DIV','P','BR','STRONG','EM','B','I','U','S','BLOCKQUOTE','UL','OL','LI','A','H2','H3','PRE','CODE']);
    for (const el of [...doc.body.querySelectorAll('*')].reverse()) {
      if (!allowed.has(el.tagName)) { el.replaceWith(...el.childNodes); continue; }
      for (const attr of [...el.attributes]) {
        if (!(el.tagName === 'A' && attr.name === 'href' && /^(https?:|mailto:|\/[^/]|#)/i.test(attr.value))) el.removeAttribute(attr.name);
      }
    }
    editor.innerHTML = doc.body.innerHTML;
    textarea.hidden = true;
    textarea.required = false;
    editor.hidden = false;
    document.querySelector('.editor-toolbar').hidden = false;
    const sync = () => { textarea.value = editor.innerHTML; };
    editor.addEventListener('input', sync);
    editor.addEventListener('paste', event => {
      event.preventDefault();
      document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
      sync();
    });
    document.querySelectorAll('[data-command]').forEach(button => {
      button.addEventListener('mousedown', event => event.preventDefault());
      button.addEventListener('click', () => {
        let value = button.dataset.value || null;
        if (button.dataset.command === 'createLink') {
          value = prompt(button.dataset.prompt, 'https://');
          if (!value || !/^https?:\/\//i.test(value)) return;
        }
        editor.focus();
        document.execCommand(button.dataset.command, false, value);
        sync();
      });
    });
    textarea.form.addEventListener('submit', event => {
      sync();
      if (!editor.textContent.trim()) { event.preventDefault(); editor.focus(); }
    });
  }
})();
