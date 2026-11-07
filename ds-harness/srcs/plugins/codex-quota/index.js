import {readCodex} from './codex.js';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec = promisify(execFile);
export const name = 'local-codex-quota';
export const inject = ['connection'];
export const ROUTE = '/api/local-codex-quota';
// Return only display fields; never forward arbitrary account metadata or CLI errors.
export function displayAccounts(value) {
  if (!Array.isArray(value)) throw new Error('invalid accounts');
  return value.filter(a => a?.agent === 'codex').map(a => ({
    error: typeof a.error === 'string' ? 'Magpie 无法获取此账户的实时额度，请检查网络或重新登录后刷新。' : null,
    user: String(a.user ?? ''), plan: String(a.plan ?? ''), active: a.active === true,
    balance: typeof a.balance === 'string' ? a.balance : null,
    readAt: typeof a.readAt === 'string' ? a.readAt : null,
    windows: (Array.isArray(a.windows) ? a.windows : []).map(w => ({
      name: String(w.name ?? ''),
      used: typeof w.used === 'number' && Number.isFinite(w.used) ? Math.min(100, Math.max(0, w.used)) : null,
      resetsAt: typeof w.resetsAt === 'string' ? w.resetsAt : null,
    })),
  }));
}
export function createReader(run = exec) {
  let pending;
  return () => pending ??= run('magpie', ['accounts', 'codex', '--json'], {
    timeout: 20000, maxBuffer: 1024 * 1024, encoding: 'utf8',
  }).then(({stdout}) => displayAccounts(JSON.parse(stdout))).finally(() => { pending = undefined; });
}
export function createSourceReader(magpie = createReader(), codex = readCodex) {
  const pending = new Map();
  return source => {
    if (!['magpie', 'codex'].includes(source)) return Promise.reject(new Error('Unsupported quota source'));
    if (!pending.has(source)) pending.set(source, Promise.resolve().then(() => source === 'magpie' ? magpie() : codex()).finally(() => pending.delete(source)));
    return pending.get(source);
  };
}
export function apply(ctx) {
  const read = createSourceReader();
  ctx.connection.fetch.register({path: ROUTE, methods: ['GET'], requestBody: 'buffered', fetch: async request => {
    const source = new URL(request.url).searchParams.get('source');
    if (!['magpie','codex'].includes(source)) return Response.json({error:'不支持的额度来源'}, {status:400});
    try {
      return Response.json({source, accounts: await read(source)}, {headers: {'Cache-Control': 'no-store'}});
    } catch {
      return Response.json({error: source === 'magpie' ? '无法读取 Magpie 的 Codex 额度，请检查登录状态和网络后重试。' : '无法读取 Codex CLI 订阅额度，请检查 codex 登录状态和网络后重试。'}, {status: 503, headers: {'Cache-Control': 'no-store'}});
    }
  }});
}
