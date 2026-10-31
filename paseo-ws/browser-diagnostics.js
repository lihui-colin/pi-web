// Temporary diagnostics: connection events only; never log cookies, storage values or messages.
(()=>{
  const base=performance.now();let count=0;
  function report(event,detail=''){
    if(count++>50)return;
    const safe=String(detail).replace(/(?:wss?|https?):\/\/[^\s]+/g,'[url]').replace(/(?:token|password|credential|secret)[=:][^\s,;]+/gi,'[redacted]').slice(0,180);
    fetch('/_paseo-check/report/app/'+encodeURIComponent(event)+'/'+Math.round(performance.now()-base)+'/'+encodeURIComponent(safe),{cache:'no-store'}).catch(()=>{});
  }
  const warn=console.warn;
  console.warn=function(...args){
    if(typeof args[0]==='string'&&args[0].startsWith('[HostRuntime]')){
      const error=args[1]?.error;
      report('host-warning',args[0]+' '+(error?.name||'')+' '+(error?.message||''));
    }
    return warn.apply(this,args);
  };
  addEventListener('error',e=>report('error',e.message||'resource error'));
  addEventListener('unhandledrejection',e=>report('rejection',e.reason?.message||e.reason?.name||'unknown'));
  const Native=globalThis.WebSocket;
  globalThis.WebSocket=new Proxy(Native,{construct(Target,args){
    const socket=Reflect.construct(Target,args);
    let protocol='unknown';try{protocol=new URL(String(args[0]),location.href).protocol;}catch{}
    report('ws-create',protocol);
    socket.addEventListener('open',()=>report('ws-open',protocol));
    socket.addEventListener('error',()=>report('ws-error',protocol));
    socket.addEventListener('close',e=>report('ws-close',String(e.code)));
    return socket;
  }});
  report('loaded');
  addEventListener('DOMContentLoaded',()=>{
    const hint=globalThis.__PASEO_INITIAL_DAEMON_CONNECTION__;
    report('hint',hint?'tls='+hint.useTls:'missing');
  });
})();
