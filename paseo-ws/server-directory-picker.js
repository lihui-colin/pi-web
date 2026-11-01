/* Server-side directory picker for the Paseo web Add Project flow. */
(() => {
  'use strict';
  let active = null;
  // Register before the app's overlay keyboard handlers. Native dialog owns focus.
  window.addEventListener('keydown', event => {
    if (!active) return;
    if (event.key === 'Escape') { event.preventDefault(); active.close(null); }
    else active.key(event);
    event.stopImmediatePropagation();
  }, true);

  globalThis.__paseoPickServerDirectory = (client, options = {}) => {
    if (!client || typeof client.listDirectory !== 'function') return Promise.reject(new Error('Host is unavailable'));
    if (active) return Promise.reject(new Error('A directory picker is already open'));
    return new Promise(resolve => {
      const previousFocus = document.activeElement;
      const dialog = document.createElement('dialog');
      dialog.className = 'paseo-directory-picker';
      dialog.setAttribute('aria-labelledby', 'paseo-directory-picker-title');
      dialog.innerHTML = `<style>
.paseo-directory-picker{color-scheme:dark;box-sizing:border-box;background:#1c1c1e;color:#ededed;border:1px solid #454549;border-radius:14px;padding:0;width:620px;max-width:calc(100vw - 24px);height:650px;max-height:calc(100dvh - 32px);font:14px/1.5 system-ui,sans-serif;box-shadow:0 20px 70px #0008;overflow:hidden}
.paseo-directory-picker::backdrop{background:#0009}
.paseo-directory-picker *{box-sizing:border-box}
.paseo-directory-picker .dp-shell{height:100%;display:flex;flex-direction:column}
.paseo-directory-picker header,.paseo-directory-picker footer{padding:16px;border-bottom:1px solid #38383c;flex-shrink:0}
.paseo-directory-picker h2{font-size:18px;margin:0 0 4px}
.paseo-directory-picker p{margin:0;color:#aaa;overflow-wrap:anywhere}
.paseo-directory-picker button{font:inherit;color:inherit;background:#29292d;border:1px solid #48484d;border-radius:7px;min-height:38px;padding:6px 10px;cursor:pointer}
.paseo-directory-picker button:hover{background:#35353c}
.paseo-directory-picker button:focus-visible,.paseo-directory-picker [role=treeitem]:focus-visible{outline:2px solid #85b7ff;outline-offset:-2px}
.paseo-directory-picker button:disabled{opacity:.45;cursor:default}
.paseo-directory-picker .dp-toolbar{display:flex;gap:8px;padding:12px 16px;align-items:center;flex-wrap:wrap}
.paseo-directory-picker .dp-tree{flex:1;min-height:80px;overflow:auto;padding:0 12px 12px}
.paseo-directory-picker .dp-row{display:flex;align-items:center;min-height:42px;border-radius:6px;min-width:max-content}
.paseo-directory-picker .dp-row[aria-selected=true]{background:#26476c}
.paseo-directory-picker .dp-row button{border:0;background:transparent;text-align:left}
.paseo-directory-picker .dp-toggle{width:38px;flex-shrink:0;padding:6px}
.paseo-directory-picker .dp-name{flex:1;min-width:80px}
.paseo-directory-picker .dp-note{padding:8px 12px;color:#aaa}
.paseo-directory-picker .dp-error{color:#ffb8ad}
.paseo-directory-picker footer{border-top:1px solid #38383c;border-bottom:0}
.paseo-directory-picker .dp-selected{display:block;max-height:65px;overflow:auto;overflow-wrap:anywhere;margin:4px 0 12px}
.paseo-directory-picker .dp-actions{display:flex;justify-content:flex-end;gap:8px}
.paseo-directory-picker .dp-confirm{background:#2563a6;border-color:#5287c4}
@media(prefers-color-scheme:light){.paseo-directory-picker{color-scheme:light;background:#fff;color:#202025}.paseo-directory-picker p,.paseo-directory-picker .dp-note{color:#62626d}.paseo-directory-picker button{background:#f3f3f6;border-color:#ccc}.paseo-directory-picker button:hover{background:#e6e6ee}.paseo-directory-picker .dp-row[aria-selected=true]{background:#dceaff}.paseo-directory-picker .dp-confirm{background:#2563a6;color:white}.paseo-directory-picker .dp-error{color:#a32419}}
</style><div class="dp-shell"><header><h2 id="paseo-directory-picker-title">Browse server folders</h2><p class="dp-host"></p></header><div class="dp-toolbar"><button type="button" class="dp-up">↑ Parent folder</button><button type="button" class="dp-retry">Refresh</button></div><div class="dp-tree" role="tree" aria-label="Server folders"></div><footer><p>Selected folder</p><strong class="dp-selected" aria-live="polite"></strong><div class="dp-actions"><button type="button" class="dp-cancel">Cancel</button><button type="button" class="dp-confirm">Select this folder</button></div></footer></div>`;
      const find = selector => dialog.querySelector(selector);
      const tree = find('.dp-tree'), selectedText = find('.dp-selected');
      find('.dp-host').textContent = options.hostLabel ? 'Folders on ' + options.hostLabel : 'Folders on the connected server';
      const cache = new Map(), expanded = new Set(), pending = new Set();
      let closed = false, generation = 0, root = '/', selected = '/';
      const canonical = value => '/' + value.split('/').filter(Boolean).join('/');
      const parent = value => value.slice(0, value.lastIndexOf('/')) || '/';
      function button(text, action, className) {
        const el = document.createElement('button'); el.type = 'button'; el.textContent = text;
        if (className) el.className = className;
        el.onclick = action; return el;
      }
      function close(value) {
        if (closed) return;
        closed = true; active = null;
        dialog.close(); dialog.remove();
        if (previousFocus?.isConnected) previousFocus.focus();
        resolve(value);
      }
      function focusPath(path) {
        [...tree.querySelectorAll('[role=treeitem]')].find(row => row.dataset.path === path)?.focus();
      }
      async function load(path) {
        if (closed || pending.has(path) || cache.has(path)) return;
        const epoch = generation;
        pending.add(path); render();
        try {
          // Root at the actual absolute folder. Returned entry paths are relative to it.
          const result = await client.listDirectory(path, '.');
          if (closed || generation !== epoch) return;
          if (!Array.isArray(result?.entries)) throw new Error('The server returned an invalid folder list');
          const entries = result.entries.filter(entry => entry.kind === 'directory' && typeof entry.name === 'string' && entry.name !== '.' && entry.name !== '..' && !entry.name.includes('/'));
          entries.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
          cache.set(path, { entries });
        } catch (error) {
          if (closed || generation !== epoch) return;
          cache.set(path, { error: 'Unable to read this folder. Check permissions and host connection.' });
        } finally {
          if (!closed && generation === epoch) { pending.delete(path); render(); }
        }
      }
      function navigate(path) {
        root = canonical(path); selected = root; expanded.clear(); expanded.add(root);
        render(); focusPath(root); void load(root);
      }
      function toggle(path) {
        if (expanded.has(path)) {
          expanded.delete(path);
          if (selected.startsWith(path === '/' ? '/' : path + '/')) selected = path;
        }
        else { expanded.add(path); void load(path); }
        render(); focusPath(path);
      }
      function selectAndExpand(path) {
        selected = path;
        expanded.add(path);
        void load(path);
        render(); focusPath(path);
      }
      function render() {
        if (closed) return;
        const focused = tree.contains(document.activeElement) ? document.activeElement.closest('[data-path]')?.dataset.path : null;
        tree.replaceChildren();
        find('.dp-up').disabled = selected === '/';
        selectedText.textContent = selected;
        find('.dp-confirm').disabled = !cache.has(root) || Boolean(cache.get(root)?.error) || Boolean(cache.get(selected)?.error);
        function add(path, level) {
          const row = document.createElement('div'); row.className = 'dp-row'; row.dataset.path = path;
          row.setAttribute('role', 'treeitem'); row.setAttribute('aria-level', String(level + 1));
          row.setAttribute('aria-label', path === '/' ? 'Root folder' : path.split('/').pop());
          row.setAttribute('aria-expanded', String(expanded.has(path)));
          row.setAttribute('aria-selected', String(selected === path)); row.tabIndex = selected === path ? 0 : -1;
          row.style.paddingLeft = Math.min(level, 12) * 18 + 'px';
          const toggleButton = button(expanded.has(path) ? '▾' : '▸', () => toggle(path), 'dp-toggle');
          toggleButton.tabIndex = -1;
          toggleButton.setAttribute('aria-label', (expanded.has(path) ? 'Collapse ' : 'Expand ') + path);
          const name = button(path === '/' ? '/' : path.split('/').pop(), () => selectAndExpand(path), 'dp-name');
          const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('width', '17'); icon.setAttribute('height', '17'); icon.setAttribute('aria-hidden', 'true');
          icon.style.cssText = 'vertical-align:-3px;margin-right:8px';
          icon.innerHTML = '<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>';
          name.prepend(icon);
          name.tabIndex = -1;
          row.append(toggleButton, name); tree.append(row);
          if (!expanded.has(path)) return;
          const data = cache.get(path);
          if (!data || data.error || data.entries.length === 0) {
            const note = document.createElement('div'); note.className = 'dp-note' + (data?.error ? ' dp-error' : '');
            note.setAttribute('role', data?.error ? 'alert' : 'status');
            note.textContent = data?.error || (data ? 'No subfolders' : 'Loading folders…');
            if (data?.error) note.append(button('Retry', () => { cache.delete(path); void load(path); }));
            tree.append(note);
          } else {
            for (const entry of data.entries) add(canonical(path + '/' + entry.name), level + 1);
          }
        }
        add(root, 0);
        if (focused) focusPath(focused);
      }
      function key(event) {
        const row = event.target.closest?.('[role=treeitem]');
        if (!row || !tree.contains(row)) return;
        const path = row.dataset.path, rows = [...tree.querySelectorAll('[role=treeitem]')], index = rows.indexOf(row);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault(); rows[Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))].focus();
        } else if (event.key === 'ArrowRight') {
          event.preventDefault();
          if (!expanded.has(path)) toggle(path);
          else if (Number(rows[index + 1]?.getAttribute('aria-level')) > Number(row.getAttribute('aria-level'))) rows[index + 1].focus();
        } else if (event.key === 'ArrowLeft') {
          event.preventDefault(); if (expanded.has(path)) toggle(path); else focusPath(parent(path));
        } else if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault(); selectAndExpand(path);
        } else if (event.key === 'Home' || event.key === 'End') {
          event.preventDefault(); rows[event.key === 'Home' ? 0 : rows.length - 1]?.focus();
        }
      }
      find('.dp-up').onclick = () => navigate(parent(selected));
      find('.dp-retry').onclick = () => { generation++; cache.clear(); pending.clear(); expanded.clear(); expanded.add(root); selected = root; render(); void load(root); };
      find('.dp-cancel').onclick = () => close(null);
      find('.dp-confirm').onclick = () => close(selected);
      dialog.addEventListener('cancel', e => { e.preventDefault(); close(null); });
      dialog.addEventListener('click', e => { e.stopPropagation(); });
      document.body.append(dialog); active = { close, key };
      dialog.showModal();
      navigate(typeof options.initialPath === 'string' && options.initialPath.startsWith('/') ? options.initialPath : '/');
    });
  };
})();
