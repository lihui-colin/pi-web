window.__ModuleLoader__.load({id: '@local/dsh-codex-quota', factory: require => {
  const React = require('react');
  const h = React.createElement;
  const css = `
.dsh-quota-panel{border-top:1px solid var(--dsw-alias-border-l2,#8884);margin-top:12px;padding-top:12px;font:inherit;overflow-wrap:anywhere}
.dsh-quota-action{font:inherit;color:inherit;border:0;background:transparent;cursor:pointer;padding:2px 6px;border-radius:6px}
.dsh-quota-action:hover{background:#8882}.dsh-quota-action:focus-visible{outline:2px solid #70b483}.dsh-quota-action:disabled{opacity:.5;cursor:wait}
.dsh-quota-row{display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap}.dsh-quota-muted{color:var(--dsw-alias-label-secondary,#a1a7a3)}
.dsh-quota-account{border-top:1px solid #8884;margin-top:10px;padding-top:10px}.dsh-quota-plan{border:1px solid #8888;border-radius:20px;padding:0 6px;margin-left:6px}
.dsh-quota-panel progress{display:block;width:100%;height:6px;appearance:none;border:0;border-radius:6px;overflow:hidden;accent-color:#70b483;margin:4px 0 10px}
.dsh-quota-panel progress::-webkit-progress-bar{background:#8885;border-radius:6px}.dsh-quota-panel progress::-webkit-progress-value{background:#70b483;border-radius:6px}
.dsh-quota-footer{font-size:11px;margin-top:10px;overflow-wrap:anywhere}
`;
  function until(value) {
    const ms = Date.parse(value) - Date.now();
    if (!Number.isFinite(ms)) return '重置时间未知';
    if (ms <= 0) return '即将重置';
    const hours = Math.ceil(ms / 3600000);
    return `将在 ${hours >= 24 ? Math.ceil(hours / 24) + '天' : hours + '小时'}后重置`;
  }
  function updated(value) {
    const minutes = Math.floor((Date.now() - Date.parse(value)) / 60000);
    return !Number.isFinite(minutes) ? '未知' : minutes <= 0 ? '刚刚' : minutes < 60 ? `${minutes}分钟前` : new Date(value).toLocaleString();
  }
  function balance(value) {
    const match = /^(\d+(?:\.\d+)?)\s*credits$/i.exec(value || '');
    return match ? Number(match[1]).toLocaleString(undefined, {maximumFractionDigits: 2}) : value ?? '未知';
  }
  function quotaSource(selection) {
    if (!selection) return null;
    if (/^magpie(?:-|$)/i.test(selection.provider ?? '') && /^codex\//i.test(selection.model ?? '')) return 'magpie';
    if (['codex', 'openai-codex'].includes(selection.provider)) return 'codex';
    return null;
  }
  function QuotaDock({useProjection}) {
    const model = useProjection('modelSelection');
    const selection = model?.next ?? model?.lastUsed;
    const source = quotaSource(selection);
    return source ? h(QuotaPanel, {key:source + ':' + selection.provider + ':' + selection.model, source}) : null;
  }
  function QuotaPanel({source}) {
    const [busy, setBusy] = React.useState(false);
    const [accounts, setAccounts] = React.useState(null);
    const [error, setError] = React.useState('');
    const request = React.useRef(null);
    const id = React.useId();
    async function refresh() {
      if (request.current) return;
      const controller = new AbortController(); request.current = controller;
      setBusy(true); setError('');
      try {
        const response = await fetch('/api/local-codex-quota?source=' + source, {signal: controller.signal, cache: 'no-store'});
        const body = await response.json();
        if (!response.ok || !Array.isArray(body.accounts)) {
          const fallback = response.status === 404 ? '接口尚未加载，请重新加载 DSH 插件后重试。'
            : response.status === 401 ? '登录已失效，请重新打开 DSH 页面后重试。'
            : '额度查询失败，请检查登录状态和网络后重试。';
          throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
        }
        setAccounts(body.accounts);
      } catch (e) {
        if (e.name !== 'AbortError') setError(e instanceof SyntaxError ? '额度接口返回了网页内容，请检查 DSH 插件是否已加载。' : e.message || '额度查询失败，请稍后重试。');
      } finally { if (request.current === controller) {request.current = null; setBusy(false);} }
    }
    React.useEffect(() => { void refresh(); return () => request.current?.abort(); }, []);
    return h('section', {className:'dsh-quota-panel', role:'region', 'aria-labelledby':id},
        h('div', {className:'dsh-quota-row'}, h('strong', {id}, 'Codex 额度'),
          h('button', {type:'button',className:'dsh-quota-action',disabled:busy,onClick:refresh,'aria-label':'刷新 Codex 额度'}, busy ? '查询中…' : '↻ 刷新')),
        error && h('p', {role:'alert'}, error),
        busy && !accounts && h('p', {role:'status'}, '正在查询额度…'),
        accounts?.length === 0 && h('p', null, source === 'magpie' ? '未发现 Codex 订阅账户，请先在 Magpie 中登录。' : '未发现 Codex 订阅账户，请先运行 codex login。'),
        accounts?.map((account, index) => h('article', {className:'dsh-quota-account', key:account.user + index},
          h('div', null, h('strong', null, 'Codex'), h('span', {className:'dsh-quota-plan'}, account.plan || '未知套餐')),
          account.error && h('p', {role:'alert'}, account.error),
          account.windows.map((w, i) => h('div', {key:i, style:{marginTop:16}},
            h('div', {className:'dsh-quota-row'}, h('span', {className:'dsh-quota-muted'}, w.name === '7 days' ? '每周' : w.name), h('span', {title:w.resetsAt ? new Date(w.resetsAt).toLocaleString() : undefined}, h('strong', null, w.used === null ? '用量未知' : `已使用 ${w.used}%`), ' · ', until(w.resetsAt))),
            h('progress', {max:100, value:w.used ?? undefined, 'aria-label': `${w.name}已用额度`}))),
          !account.windows.length && h('p', null, '暂未返回额度窗口'),
          h('div', {className:'dsh-quota-row'}, h('span', {className:'dsh-quota-muted'}, '积分'), h('strong', null, `剩余 ${balance(account.balance)}`)),
          h('div', {className:'dsh-quota-row dsh-quota-footer dsh-quota-muted'}, h('span', null, account.user), h('span', {title:account.readAt ?? ''}, `更新于 ${updated(account.readAt)}`))
        )));
  }
  return {inject:['slots'], apply(ctx) {
    ctx.effect(() => {const style = document.createElement('style'); style.textContent = css; document.head.append(style); return () => style.remove();});
    ctx.slots.inject('conversation.context.details', () => ctx.slots.register({name:'conversation.context.details', id:'local-codex-quota', order:90}, QuotaDock));
  }};
}});
