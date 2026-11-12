/* DSH DirectoryBrowser interaction adapted to Paseo's connected-host file API.
 * Reference: @deepseek-ai/dsh-client-ui-directory-picker-browse/lib/client.js.
 * A selected folder anchors two columns: its siblings and its children.
 */
(() => {
  'use strict';
  let active = null;
  window.addEventListener('keydown', event => {
    if (!active) return;
    // Let the native dialog keep Tab handling; isolate the underlying app shortcuts.
    if (!event.isComposing && event.keyCode !== 229) active.key(event);
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
.paseo-directory-picker{color-scheme:inherit;--dp-bg:var(--colors-surface0, #1c1c1e);--dp-text:var(--colors-foreground, #ededed);--dp-muted:var(--colors-foreground-muted, #aaa);--dp-border:var(--colors-border, #38383c);--dp-hover:var(--colors-surface1, #303034);--dp-selected:var(--colors-surface4, #26476c);--dp-error:var(--colors-destructive, #ffb8ad);box-sizing:border-box;background:var(--dp-bg);color:var(--dp-text);border:1px solid var(--dp-border);border-radius:12px;padding:0;width:680px;max-width:calc(100vw - 24px);height:500px;max-height:calc(100dvh - 32px);font:13px/1.5 system-ui,sans-serif;box-shadow:0 20px 70px #0008;overflow:hidden}
.paseo-directory-picker::backdrop{background:#0009}
.paseo-directory-picker *{box-sizing:border-box;scrollbar-color:var(--dp-muted) var(--dp-bg)}
.paseo-directory-picker .dp-shell{height:100%;display:flex;flex-direction:column}
.paseo-directory-picker header{padding:16px 24px 8px;border-bottom:1px solid var(--dp-border);flex-shrink:0}
.paseo-directory-picker h2{font-size:16px;line-height:24px;margin:0 0 4px;font-weight:550}
.paseo-directory-picker p{margin:0;color:var(--dp-muted);overflow-wrap:anywhere}
.paseo-directory-picker button{font:inherit;color:inherit;background:transparent;border:1px solid var(--dp-border);border-radius:5px;min-height:30px;padding:4px 10px;cursor:pointer}
.paseo-directory-picker button:hover{background:var(--dp-hover)}
.paseo-directory-picker button:focus-visible,.paseo-directory-picker input:focus-visible{outline:2px solid var(--colors-accent, #85b7ff);outline-offset:-2px}
.paseo-directory-picker button:disabled{opacity:.45;cursor:default}
.paseo-directory-picker .dp-crumbbar{display:flex;align-items:center;gap:4px;min-height:30px;min-width:0}
.paseo-directory-picker .dp-crumbs{display:flex;align-items:center;gap:4px;overflow:auto;white-space:nowrap;scrollbar-width:none}
.paseo-directory-picker .dp-crumbs button{border:0;padding:0 3px;color:var(--dp-muted);max-width:160px;overflow:hidden;text-overflow:ellipsis;flex-shrink:0}
.paseo-directory-picker .dp-edit{border:0;flex:1;min-width:34px;text-align:right}
.paseo-directory-picker input{font:inherit;background:transparent;color:inherit;border:1px solid var(--dp-border);border-radius:5px;padding:5px 8px;min-width:0}
.paseo-directory-picker .dp-path{width:100%}
.paseo-directory-picker [hidden]{display:none!important}
.paseo-directory-picker .dp-content{flex:1;min-height:0;display:flex;flex-direction:column;padding:16px 16px 12px 24px;position:relative}
.paseo-directory-picker .dp-columns{display:flex;gap:12px;flex:1;min-height:0;overflow-x:auto}
.paseo-directory-picker .dp-column{display:flex;flex-direction:column;gap:2px;flex:1 0 256px;min-width:256px;overflow-y:auto;padding-right:8px}
.paseo-directory-picker .dp-column+.dp-column{border-left:1px solid var(--dp-border);padding-left:12px}
.paseo-directory-picker .dp-row{display:flex;align-items:center;gap:6px;border:0;flex-shrink:0;text-align:left;width:100%;height:30px;padding:4px}
.paseo-directory-picker .dp-row[aria-current=true]{background:var(--dp-selected)}
.paseo-directory-picker .dp-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.paseo-directory-picker .dp-note{padding:4px;color:var(--dp-muted)}
.paseo-directory-picker .dp-error{color:var(--dp-error);padding-top:8px}
.paseo-directory-picker .dp-loading{position:absolute;bottom:8px;right:16px;background:var(--dp-bg);padding:2px 8px}
.paseo-directory-picker footer{display:flex;align-items:center;flex-wrap:wrap;gap:8px;border-top:1px solid var(--dp-border);padding:16px 24px;flex-shrink:0}
.paseo-directory-picker .dp-hidden{border:0;padding:4px 0;color:var(--dp-muted)}
.paseo-directory-picker .dp-hidden[aria-pressed=true]{color:var(--dp-text)}
.paseo-directory-picker .dp-gap{flex:1}
.paseo-directory-picker .dp-confirm{background:var(--colors-primary, #2563a6);border-color:var(--colors-border-accent, #5287c4);color:var(--colors-primary-foreground, #fff);min-width:72px}
.paseo-directory-picker .dp-create{position:absolute;inset:0;background:var(--dp-bg);padding:24px;display:flex;flex-direction:column;justify-content:center;gap:12px}
.paseo-directory-picker .dp-up{display:none}
.paseo-directory-picker .dp-create-actions{display:flex;justify-content:flex-end;gap:8px}
@media(max-width:600px){
.paseo-directory-picker{width:100%;max-width:calc(100vw - 16px);height:calc(100dvh - 16px);max-height:calc(100dvh - 16px);font-size:15px}
.paseo-directory-picker header{padding:12px 12px 6px}
.paseo-directory-picker .dp-content{padding:8px 12px;min-height:80px}
.paseo-directory-picker .dp-columns{overflow-x:hidden;gap:0}
.paseo-directory-picker .dp-column{min-width:0;flex:1 1 100%;padding:0}
.paseo-directory-picker .dp-columns:has(.dp-column+.dp-column) .dp-column:first-child{display:none}
.paseo-directory-picker .dp-column+.dp-column{border:0;padding:0}
.paseo-directory-picker button{min-height:44px}
.paseo-directory-picker .dp-row{height:48px;padding:8px 4px}
.paseo-directory-picker .dp-up{display:block;flex-shrink:0;text-align:left;border:0;margin-bottom:4px}
.paseo-directory-picker .dp-edit{flex:0 0 44px}
.paseo-directory-picker .dp-crumbs{flex:1;min-width:0}
.paseo-directory-picker input{font-size:16px;min-height:44px}
.paseo-directory-picker footer{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));padding:8px 12px max(8px,env(safe-area-inset-bottom));gap:8px}
.paseo-directory-picker .dp-hidden{grid-column:1/-1;justify-self:start}
.paseo-directory-picker .dp-gap{display:none}
.paseo-directory-picker .dp-create{padding:16px;overflow-y:auto}
}
@media(prefers-color-scheme:light){.paseo-directory-picker{--dp-bg:var(--colors-surface0, #fff);--dp-text:var(--colors-foreground, #202025);--dp-muted:var(--colors-foreground-muted, #62626d);--dp-border:var(--colors-border, #ddd);--dp-hover:var(--colors-surface1, #f0f0f4);--dp-selected:var(--colors-surface4, #dceaff);--dp-error:var(--colors-destructive, #a32419)}}
</style><div class="dp-shell"><header><h2 id="paseo-directory-picker-title">Open folder</h2><p class="dp-host"></p><div class="dp-crumbbar"><nav class="dp-crumbs" aria-label="Folder path"></nav><button class="dp-edit" type="button" aria-label="Edit path">✎</button><input class="dp-path" aria-label="Folder path" spellcheck="false" autocomplete="off" hidden></div></header><div class="dp-content"><button type="button" class="dp-up">↑ Parent folder</button><div class="dp-columns" aria-label="Server folders"></div><p class="dp-error" role="alert" hidden></p><span class="dp-loading" role="status" hidden>Loading folders…</span><div class="dp-create" role="group" aria-label="New folder" hidden><h2>New folder</h2><p class="dp-create-in"></p><input class="dp-create-name" aria-label="Folder name" autocomplete="off"><p class="dp-create-error" role="alert" hidden></p><div class="dp-create-actions"><button class="dp-create-cancel" type="button">Cancel</button><button class="dp-create-confirm" type="button">Create</button></div></div></div><footer><button class="dp-hidden" type="button" aria-pressed="false">Show hidden files</button><span class="dp-gap"></span><button class="dp-new" type="button">New folder</button><button class="dp-cancel" type="button">Cancel</button><button class="dp-confirm" type="button">Open</button></footer></div>`;
      const find = selector => dialog.querySelector(selector);
      const columns = find('.dp-columns'), crumbs = find('.dp-crumbs'), input = find('.dp-path');
      const createBox = find('.dp-create'), createInput = find('.dp-create-name');
      find('.dp-host').textContent = options.hostLabel ? 'Folders on ' + options.hostLabel : 'Folders on the connected server';
      let closed = false, sequence = 0, loading = false, slowTimer, draftTimer;
      let level = null, child = null, selected = null, showHidden = false, editing = false, creating = false, createBusy = false;
      let createParent = null;
      const canonical = value => {
        const parts = [];
        for (const part of value.split('/')) {
          if (part === '..') parts.pop();
          else if (part && part !== '.') parts.push(part);
        }
        return '/' + parts.join('/');
      };
      const parent = value => value.slice(0, value.lastIndexOf('/')) || '/';
      const join = (path, name) => canonical(path + '/' + name);
      const target = () => selected || level?.path;
      function button(text, action, className) {
        const el = document.createElement('button'); el.type = 'button'; el.textContent = text;
        if (className) el.className = className;
        el.onclick = action; return el;
      }
      function error(message) {
        find('.dp-error').textContent = message || '';
        find('.dp-error').hidden = !message;
      }
      function supersede() {
        clearTimeout(draftTimer); clearTimeout(slowTimer);
        find('.dp-loading').hidden = true;
        loading = false;
        return ++sequence;
      }
      function close(value) {
        if (closed || createBusy) return;
        closed = true; supersede(); active = null;
        dialog.close(); dialog.remove();
        if (previousFocus?.isConnected) previousFocus.focus();
        resolve(value);
      }
      async function list(path) {
        const result = await client.listDirectory(path, '.');
        if (!Array.isArray(result?.entries)) throw new Error('The server returned an invalid folder list');
        const entries = result.entries.filter(entry => entry.kind === 'directory' && typeof entry.name === 'string' && entry.name && entry.name !== '.' && entry.name !== '..' && !/[\x00/]/.test(entry.name));
        entries.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
        return { path, entries };
      }
      function begin() {
        const seq = supersede(); loading = true; error(null);
        slowTimer = setTimeout(() => { if (!closed && seq === sequence) find('.dp-loading').hidden = false; }, 300);
        updateActions(); return seq;
      }
      function finish(seq) {
        if (closed || seq !== sequence) return false;
        loading = false; clearTimeout(slowTimer); find('.dp-loading').hidden = true;
        return true;
      }
      // Keep the readable view while a new path loads. A slow parent cannot hold
      // the target hostage; a late parent upgrades it only under the same intent.
      async function navigate(path, { preview = false } = {}) {
        path = canonical(path);
        const seq = begin();
        try {
          const next = await list(path);
          if (closed || seq !== sequence) return;
          const commit = upper => {
            if (closed || seq !== sequence) return;
            const match = upper?.entries.some(entry => join(upper.path, entry.name) === path);
            level = match ? upper : next; selected = match ? path : null; child = match ? next : null;
            finish(seq);
            if (!preview) editing = false;
            render();
          };
          if (path === '/') commit(null);
          else {
            const parentScan = list(parent(path)).catch(() => null);
            const upper = await Promise.race([parentScan, new Promise(resolve => setTimeout(() => resolve(null), 200))]);
            commit(upper);
            if (!upper) void parentScan.then(value => { if (value) commit(value); });
          }
        } catch (reason) {
          if (!finish(seq)) return;
          render();
          if (!preview) error('Unable to read this folder. Check the path, permissions and host connection.');
        }
      }
      async function pick(path, source) {
        if (selected === path && child && !loading) return;
        const seq = begin(); editing = false;
        level = source; selected = path; child = null; render();
        try {
          const next = await list(path);
          if (!finish(seq)) return;
          child = next; render();
        } catch (reason) {
          if (!finish(seq)) return;
          selected = null; render();
          error('Unable to read this folder. Check permissions and host connection.');
          find('.dp-edit').focus();
        }
      }
      function focusRow(path) {
        [...columns.querySelectorAll('[data-path]')].find(row => row.dataset.path === path)?.focus();
      }
      function updateActions() {
        find('header').inert = creating;
        find('footer').inert = creating;
        find('.dp-confirm').disabled = !target() || loading || editing || creating;
        find('.dp-new').disabled = !target() || loading || editing || creating || typeof client.createFileEntry !== 'function';
        find('.dp-cancel').disabled = createBusy;
        find('.dp-hidden').disabled = creating;
        find('.dp-edit').disabled = creating;
        find('.dp-up').disabled = creating || !target() || target() === '/';
      }
      function render() {
        if (closed) return;
        const focus = columns.contains(document.activeElement) ? document.activeElement.dataset.path : null;
        input.hidden = !editing; crumbs.hidden = editing; find('.dp-edit').hidden = editing;
        crumbs.replaceChildren();
        const path = target() || '/';
        let prefix = '';
        for (const name of ['/', ...path.split('/').filter(Boolean)]) {
          prefix = name === '/' ? '/' : join(prefix, name);
          const crumbPath = prefix;
          if (crumbs.childNodes.length) crumbs.append(document.createTextNode('›'));
          crumbs.append(button(name, () => { if (!creating) void navigate(crumbPath); }));
        }
        crumbs.scrollLeft = crumbs.scrollWidth;
        columns.replaceChildren();
        const tail = editing ? input.value.slice(input.value.lastIndexOf('/') + 1).toLowerCase() : '';
        for (const listing of [level, ...(selected ? [child] : [])]) {
          const column = document.createElement('div'); column.className = 'dp-column';
          column.setAttribute('role', 'list'); column.setAttribute('aria-label', listing?.path || selected || 'Server folders');
          columns.append(column);
          if (!listing) {
            const note = document.createElement('span'); note.className = 'dp-note'; note.textContent = loading ? 'Loading folders…' : 'Choose a folder path'; column.append(note); continue;
          }
          const filterTail = editing && listing === (child || level) ? tail : '';
          const displayable = entry => showHidden || !entry.name.startsWith('.') || filterTail.startsWith('.');
          const matches = entry => displayable(entry) && entry.name.toLowerCase().startsWith(filterTail);
          const narrowing = filterTail && listing.entries.some(matches);
          const visible = listing.entries.filter(entry => join(listing.path, entry.name) === selected || (narrowing ? matches(entry) : showHidden || !entry.name.startsWith('.')));
          for (const entry of visible) {
            const entryPath = join(listing.path, entry.name);
            const seat = document.createElement('div'); seat.setAttribute('role', 'listitem');
            const row = button('', () => { if (!creating) void pick(entryPath, listing); }, 'dp-row');
            row.dataset.path = entryPath; row.setAttribute('aria-label', entry.name); row.setAttribute('aria-current', String(entryPath === selected));
            const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('width', '16'); icon.setAttribute('height', '16'); icon.setAttribute('aria-hidden', 'true');
            icon.innerHTML = '<path d="M3 7V5h6l2 2h10v13H3Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>';
            const name = document.createElement('span'); name.className = 'dp-name'; name.textContent = entry.name;
            const arrow = document.createElement('span'); arrow.textContent = '›'; arrow.setAttribute('aria-hidden', 'true');
            row.append(icon, name, arrow); seat.append(row); column.append(seat);
          }
          if (!visible.length) {
            const note = document.createElement('span'); note.className = 'dp-note'; note.textContent = 'No subfolders'; column.append(note);
          }
        }
        find('.dp-hidden').setAttribute('aria-pressed', String(showHidden));
        updateActions();
        if (focus) focusRow(focus);
      }
      function edit() {
        if (creating) return;
        supersede(); editing = true;
        const path = target() || '/'; input.value = path + (path === '/' ? '' : '/');
        render(); input.focus(); input.setSelectionRange(input.value.length, input.value.length);
      }
      function cancelEdit() { supersede(); editing = false; if (!child) selected = null; error(null); render(); find('.dp-edit').focus(); }
      input.addEventListener('input', () => {
        supersede(); error(null); render();
        if (!input.value.startsWith('/')) return;
        const directory = canonical(input.value.slice(0, input.value.lastIndexOf('/') + 1));
        if (directory === (child || level)?.path) return;
        draftTimer = setTimeout(() => void navigate(directory, { preview: true }), 250);
      });
      function dismissCreate() {
        if (createBusy) return;
        creating = false; createBox.hidden = true; columns.inert = false; updateActions(); find('.dp-new').focus();
      }
      async function create() {
        const name = createInput.value;
        const message = find('.dp-create-error');
        if (!name.trim() || name !== name.trim() || name === '.' || name === '..' || /[\x00/\\]/.test(name)) {
          message.textContent = 'Enter a folder name without path separators.'; message.hidden = false; return;
        }
        if (createBusy) return;
        createBusy = true; find('.dp-create-confirm').disabled = true; find('.dp-create-cancel').disabled = true; createInput.disabled = true; updateActions();
        try {
          const result = await client.createFileEntry({ cwd: createParent, parentPath: '.', name, kind: 'directory' });
          if (!result?.success) throw new Error(result?.error || 'Unable to create folder');
          createBusy = false; dismissCreate();
          await navigate(join(createParent, name));
        } catch (reason) {
          message.textContent = reason instanceof Error ? reason.message : 'Unable to create folder'; message.hidden = false;
        } finally {
          createBusy = false; createInput.disabled = false; find('.dp-create-confirm').disabled = false; find('.dp-create-cancel').disabled = false; updateActions();
        }
      }
      function key(event) {
        if (event.key === 'Escape') {
          event.preventDefault();
          if (creating) dismissCreate(); else if (editing) cancelEdit(); else close(null);
        } else if (creating) {
          if (event.key === 'Enter' && event.target === createInput) { event.preventDefault(); void create(); }
        } else if (editing && event.target === input) {
          if (event.key === 'Enter') {
            event.preventDefault();
            if (!input.value.startsWith('/')) error('Enter an absolute server path.');
            else void navigate(input.value);
          }
        } else if (columns.contains(event.target)) {
          const rows = [...event.target.closest('.dp-column').querySelectorAll('.dp-row')];
          const index = rows.indexOf(event.target);
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Home' || event.key === 'End') {
            event.preventDefault();
            rows[event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))]?.focus();
          } else if (event.key === 'ArrowRight') { event.preventDefault(); event.target.click(); }
          else if (event.key === 'ArrowLeft' && level) { event.preventDefault(); void navigate(parent(target())); }
        }
      }
      find('.dp-up').onclick = () => void navigate(parent(target()));
      find('.dp-edit').onclick = edit;
      find('.dp-hidden').onclick = () => { showHidden = !showHidden; render(); };
      find('.dp-new').onclick = () => {
        supersede(); creating = true; createParent = target(); createBox.hidden = false; columns.inert = true;
        find('.dp-create-in').textContent = 'Create in ' + createParent;
        find('.dp-create-error').hidden = true; createInput.value = ''; updateActions(); createInput.focus();
      };
      find('.dp-create-confirm').onclick = () => void create();
      find('.dp-create-cancel').onclick = dismissCreate;
      find('.dp-cancel').onclick = () => close(null);
      find('.dp-confirm').onclick = () => { if (!find('.dp-confirm').disabled) close(target()); };
      dialog.addEventListener('cancel', event => { event.preventDefault(); if (creating) dismissCreate(); else if (editing) cancelEdit(); else close(null); });
      dialog.addEventListener('click', event => event.stopPropagation());
      document.body.append(dialog); active = { key }; dialog.showModal();
      render();
      void navigate(typeof options.initialPath === 'string' && options.initialPath.startsWith('/') ? options.initialPath : '/');
    });
  };
})();
