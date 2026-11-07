import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';

// A short-lived, dedicated CLI process; no thread or model turn is created.
export function readCodex(spawnCli = spawn) {
  return new Promise((resolve, reject) => {
    const child = spawnCli('codex', ['app-server', '--listen', 'stdio://'], {stdio:['pipe','pipe','ignore']});
    const lines = createInterface({input:child.stdout});
    let done = false, account, limits;
    const timer = setTimeout(() => finish(new Error('Codex quota timed out')), 20000);
    function finish(error) {
      if (done) return;
      done = true; clearTimeout(timer); lines.close(); child.stdin.destroy(); child.kill();
      if (error) reject(error);
      else {try {resolve(normalizeCodex(account, limits));} catch (e) {reject(e);}}
    }
    function send(message) { child.stdin.write(JSON.stringify(message) + '\n'); }
    child.on('error', finish);
    child.stdin.on('error', finish);
    child.on('exit', () => {if (!done) finish(new Error('Codex exited before returning quota'));});
    lines.on('line', line => {
      let message;
      try {message = JSON.parse(line);} catch {return;}
      if (![1,2,3].includes(message.id)) return;
      if (message.error) return finish(new Error('Codex account query failed'));
      if (message.id === 1) {
        send({method:'initialized'});
        send({id:2, method:'account/read', params:{refreshToken:false}});
        send({id:3, method:'account/rateLimits/read'});
      } else if (message.id === 2) account = message.result;
      else limits = message.result;
      if (account !== undefined && limits !== undefined) finish();
    });
    send({id:1,method:'initialize',params:{clientInfo:{name:'dsh_codex_quota',version:'1.0.0'}}});
  });
}
export function normalizeCodex(info, result) {
  const account = info?.account;
  const limit = result?.rateLimitsByLimitId?.codex ?? result?.rateLimits;
  if (!account || !limit) throw new Error('Codex subscription quota unavailable');
  const windows = [limit.primary, limit.secondary].filter(Boolean).map(w => ({
    name: w.windowDurationMins === 10080 ? '7 days' : `${w.windowDurationMins ?? '?'} minutes`,
    used: typeof w.usedPercent === 'number' && Number.isFinite(w.usedPercent) ? Math.max(0, Math.min(100, w.usedPercent)) : null,
    resetsAt: typeof w.resetsAt === 'number' ? new Date(w.resetsAt * 1000).toISOString() : null,
  }));
  const credits = limit.credits;
  return [{user:account.email ?? '', plan:limit.planType ?? account.planType ?? '', active:true,
    balance:credits?.unlimited ? '无限' : credits?.balance != null ? `${credits.balance} credits` : null,
    readAt:new Date().toISOString(), windows, error:null}];
}
