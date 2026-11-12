// Native composer disclosure. Provider state crosses the card and its footer
// without moving React-owned nodes or changing the input's keyboard handlers.
const DshSessionInfoContext = (0, react.createContext)(null);
const dshSessionInfoCss = `
[data-dsh-session-info],[data-dsh-session-info-value]{display:contents}
[data-dsh-session-info-trigger]{box-sizing:border-box;display:none;place-items:center;flex:none;width:32px;height:32px;padding:4px;border:0;border-radius:50%;background:transparent;color:var(--dsw-alias-label-tertiary,#92989c);cursor:pointer}
[data-dsh-session-info-trigger]:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary,#6b9cff);outline-offset:2px}
[data-dsh-session-info-trigger][aria-expanded=true]{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.15))}
/* Keep permission icon + chevron and file-upload hit targets disjoint. */
@media (max-width:1023px) and (pointer:coarse){
  [data-dsh-session-info] [data-mobile-nav="stats-ring"]{position:static!important;left:auto!important;top:auto!important;transform:none!important}
  [data-dsh-session-info] [data-mobile-nav="stats-ring-reserve"]{display:none!important}
  [data-dsh-session-info-trigger]{display:inline-grid}
  /* Only metadata controls collapse. The dock and plugin panels stay mounted and visible. */
  [data-dsh-session-info][data-open="false"]:not([data-bypass]) [data-composer-stat],
  [data-dsh-session-info][data-open="false"]:not([data-bypass]) [data-composer-plus-project],
  [data-dsh-session-info][data-open="false"]:not([data-bypass]) [data-dsh-session-info-value]{display:none!important}
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
const dshSessionInfoMobile = typeof window === "undefined" ? null : window.matchMedia("(max-width:1023px) and (pointer:coarse)");
function subscribeDshSessionInfoMobile(listener) {
  dshSessionInfoMobile?.addEventListener("change", listener);
  return () => dshSessionInfoMobile?.removeEventListener("change", listener);
}
function isDshSessionInfoMobile() { return dshSessionInfoMobile?.matches ?? false; }
function DshComposerFrame({ children, sessionId }) {
  const mobile = (0, react.useSyncExternalStore)(subscribeDshSessionInfoMobile, isDshSessionInfoMobile, () => false);
  const [open, setOpen] = (0, react.useState)(false);
  const [bypass, setBypass] = (0, react.useState)(false);
  const id = (0, react.useId)();
  // Adoption must preserve the editor (including focus and an active IME).
  // Reset only disclosure state when the session changes.
  (0, react.useLayoutEffect)(() => { setOpen(false); }, [sessionId]);
  (0, react.useEffect)(() => {
    if (!open || !mobile) return;
    const dismissOutside = event => {
      if (event.composedPath().some(node => node.id === id || node.getAttribute?.("aria-controls") === id || node.getAttribute?.("data-dsh-session-info-owner") === id)) return;
      setOpen(false);
    };
    const dismissEscape = event => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      setOpen(false);
      event.preventDefault();
      if (document.getElementById(id)?.contains(document.activeElement) || document.activeElement?.closest('[data-dsh-session-info-owner]')?.getAttribute('data-dsh-session-info-owner') === id) {
        document.querySelector(`[data-dsh-session-info-trigger][aria-controls="${id}"]`)?.focus();
      }
    };
    document.addEventListener("pointerdown", dismissOutside, true);
    document.addEventListener("keydown", dismissEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside, true);
      document.removeEventListener("keydown", dismissEscape);
    };
  }, [open, id, mobile]);
  return (0, react_jsx_runtime.jsx)(DshSessionInfoContext.Provider, {
    value: { open, setOpen, bypass, setBypass, id, mobile }, children
  });
}
function DshSessionInfoTrigger({ useProjection, t }) {
  const state = (0, react.useContext)(DshSessionInfoContext);
  const pressure = useProjection("contextPressure");
  const context = contextOccupancy(pressure);
  if (!state.mobile || state.bypass) return null;
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
  const {open, bypass, setBypass, id, mobile} = (0, react.useContext)(DshSessionInfoContext);
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
    ref, id, "data-dsh-session-info": true, "data-bypass": bypass || !mobile ? "" : undefined,
    "data-open": open ? "true" : "false", children
  });
}
function DshContextMeter(props) {
  const {mobile, id, open, bypass} = (0, react.useContext)(DshSessionInfoContext);
  const ownedProps = { ...props, dshSessionInfoOwner: id, dshSessionInfoVisible: !mobile || open || bypass };
  if (!mobile) return (0, react_jsx_runtime.jsx)(ContextMeter, ownedProps);
  return (0, react_jsx_runtime.jsx)("span", {
    "data-dsh-session-info-value": true,
    children: (0, react_jsx_runtime.jsx)(ContextMeter, ownedProps)
  });
}
