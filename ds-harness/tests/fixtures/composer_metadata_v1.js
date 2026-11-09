// Native composer disclosure. Provider state crosses the card and its footer
// without moving React-owned nodes or changing the input's keyboard handlers.
const DshSessionInfoContext = (0, react.createContext)(null);
const dshSessionInfoCss = `
[data-dsh-session-info]{box-sizing:border-box;min-width:0;width:100%;flex:none}
[data-dsh-session-info][hidden]{display:none!important}
[data-dsh-session-info][data-bypass]{display:contents}
[data-dsh-session-info-trigger]{box-sizing:border-box;display:inline-grid;place-items:center;flex:none;width:32px;height:32px;padding:4px;border:0;border-radius:50%;background:transparent;color:var(--dsw-alias-label-tertiary,#92989c);cursor:pointer}
[data-dsh-session-info-trigger]:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary,#6b9cff);outline-offset:2px}
[data-dsh-session-info-trigger][aria-expanded=true]{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.15))}
[data-dsh-session-info] [data-mobile-nav="stats-ring"]{position:static!important;left:auto!important;top:auto!important;transform:none!important}
[data-dsh-session-info] [data-mobile-nav="stats-ring-reserve"]{display:none!important}
/* Keep permission icon + chevron and file-upload hit targets disjoint. */
@media (max-width:1023px) and (pointer:coarse){
  html body [data-mobile-nav="frame"] [data-phase] [data-composer-card]:has([data-dsh-session-info-trigger]) [class*="_row"]:has(> [class*="_tools"]) > [class*="_tools"]{flex:0 0 auto!important;gap:8px!important;overflow:visible!important}
  html body [data-mobile-nav="frame"] [data-phase] [data-composer-card]:has([data-dsh-session-info-trigger]) [class*="_tools"] > [class*="_modes"]{flex:0 0 auto!important;min-width:max-content!important}
  html body [data-mobile-nav="frame"] [data-phase] [data-composer-card]:has([data-dsh-session-info-trigger]) [data-mobile-nav="file-upload"]{margin-left:0!important;margin-right:0!important}
  html body [data-mobile-nav="frame"] [data-phase] [data-composer-card]:has([data-dsh-session-info-trigger]) [data-mobile-nav="file-upload"]::after{left:0!important;right:0!important}
}
@media (max-width:350px) and (pointer:coarse){
  html body [data-mobile-nav="frame"] [data-phase] [data-composer-card]:has([data-dsh-session-info-trigger]) [class*="_row"]:has(> [class*="_tools"]){flex-wrap:wrap!important;row-gap:6px!important}
  html body [data-mobile-nav="frame"] [data-phase] [data-composer-card]:has([data-dsh-session-info-trigger]) [class*="_row"] > [class*="_trailing"]{flex-basis:100%!important}
}
`;
if (typeof document !== "undefined" && !document.querySelector('style[data-dsh-session-info-style]')) {
  const style = document.createElement("style");
  style.setAttribute("data-dsh-session-info-style", "");
  style.textContent = dshSessionInfoCss;
  document.head.appendChild(style);
}
function DshComposerFrame({ children }) {
  const [open, setOpen] = (0, react.useState)(false);
  const [bypass, setBypass] = (0, react.useState)(false);
  const id = (0, react.useId)();
  (0, react.useEffect)(() => {
    if (!open) return;
    const dismissOutside = event => {
      if (event.composedPath().some(node => node.id === id || node.getAttribute?.("aria-controls") === id)) return;
      setOpen(false);
    };
    const dismissEscape = event => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      setOpen(false);
      event.preventDefault();
      if (document.getElementById(id)?.contains(document.activeElement)) {
        document.querySelector(`[data-dsh-session-info-trigger][aria-controls="${id}"]`)?.focus();
      }
    };
    document.addEventListener("pointerdown", dismissOutside, true);
    document.addEventListener("keydown", dismissEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside, true);
      document.removeEventListener("keydown", dismissEscape);
    };
  }, [open, id]);
  return (0, react_jsx_runtime.jsx)(DshSessionInfoContext.Provider, {
    value: { open, setOpen, bypass, setBypass, id }, children
  });
}
function DshSessionInfoTrigger({ useProjection, t }) {
  const state = (0, react.useContext)(DshSessionInfoContext);
  const pressure = useProjection("contextPressure");
  const context = contextOccupancy(pressure);
  if (state.bypass) return null;
  const percent = context === null ? 0 : Math.max(0, Math.min(100, context.percent || 0));
  const label = t("composer.sessionInfo");
  return (0, react_jsx_runtime.jsx)("button", {
    type: "button", "data-dsh-session-info-trigger": true,
    "aria-label": label, "aria-expanded": state.open, "aria-controls": state.id,
    title: context === null ? label : `${label} · ${percent}%`,
    onMouseDown: event => event.preventDefault(),
    onClick: () => state.setOpen(value => !value),
    children: (0, react_jsx_runtime.jsxs)("svg", {
      width: 22, height: 22, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, "aria-hidden": true,
      children: [
        (0, react_jsx_runtime.jsx)("circle", { cx: 12, cy: 12, r: 9 }),
        (0, react_jsx_runtime.jsx)("path", { d: "M12 11v6", strokeLinecap: "round" }),
        (0, react_jsx_runtime.jsx)("circle", { cx: 12, cy: 7.5, r: 1, fill: "currentColor", stroke: "none" })
      ]
    })
  });
}
function DshComposerMetadata({ children }) {
  const ref = (0, react.useRef)(null);
  const {open, bypass, setBypass, id} = (0, react.useContext)(DshSessionInfoContext);
  (0, react.useLayoutEffect)(() => {
    const node = ref.current;
    // DS Bot replaces native metadata with a BTW queue; leave it visible.
    // Empty docks do not get a redundant information button either.
    const sync = () => setBypass(!node.querySelector('[data-composer-stat]') || node.querySelector('.bt-btw-dock') !== null);
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(node, {childList: true, subtree: true});
    return () => observer.disconnect();
  }, [setBypass]);
  return (0, react_jsx_runtime.jsx)("div", {
    ref, id, "data-dsh-session-info": true, "data-bypass": bypass ? "" : undefined,
    hidden: !open && !bypass, children
  });
}
