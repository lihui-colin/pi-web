// Verbatim excerpts from ds-bot@0.3.1/client.js (Apache-2.0).
// Upstream tag v0.3.1 / gitHead 6559c9e7c4ef71c292e6ac50f690031133536fe0.
// CSS rules retain publication order-independent anchors; functions are unmodified.
const css = `[class*="_frame"][data-sidebar-collapsed][data-rightbar-collapsed]:has(>[class*="_sidebarCol"]){grid-template-columns:0px minmax(0,1fr) 0px!important}
.bt-rail .bt-row{justify-content:center;width:56px;height:56px;min-height:56px;padding:0;border-radius:16px}
.bt-group-name>.bt-lead{margin:0 8px 0 0}
[data-composer-card] [class*="_trailing"]{gap:8px!important}
[class*="_widthHandle"]{display:none!important}
[class*="_body"]:has(> [class*="_scrollBody"]){--dsh-chat-content-width:min(960px,100%)}
[class*="_root"]:has(> [data-composer-card])>[data-composer-card]{max-width:min(992px,100%)!important}
body[data-bt-layout=flat] .bt-tools::after{display:none}
@media (hover:none){
  .bt-tools{left:auto;right:4px;margin-left:0;border-radius:999px;padding:2px;background:var(--bt-card);box-shadow:inset 0 0 0 .5px var(--bt-line-2),0 4px 14px rgba(0,0,0,.14)}
  .bt-tools::after{display:none}
  .bt-tool{width:44px;height:44px}
  .bt-menu button,.bt-menu [role=menuitem],.bt-react-strip button{min-height:44px}
  .bt-utools[data-open]{opacity:1;visibility:visible}
  .bt-utools button{width:44px;height:44px}
  [data-chat-flow-kind=user] [class*="_actions"] button{width:44px;height:44px}
}`;
var sidebarTrackWidth = () => typeof document === "undefined" ? null : document.querySelector('[class*="_sidebarCol"]')?.getBoundingClientRect().width ?? null;
function MessageTools({ text, name, sessionId, react, actions, open: tapped }) {
  const [panel, setPanel] = (0, import_react31.useState)(null);
  const [copied, setCopied] = (0, import_react31.useState)(false);
  const tools = (0, import_react31.useRef)(null);
  const pop = (0, import_react31.useRef)(null);
  const tick = useViewport();
  const close = () => setPanel(null);
  useDismiss(panel !== null, close, [tools, pop]);
  const open = (kind, event) => {
    if (panel?.kind === kind) {
      close();
      return;
    }
    setPanel({ kind, node: event.currentTarget });
  };
  const place = (0, import_react31.useMemo)(() => {
    if (!panel) return null;
    const rect = panel.node.getBoundingClientRect();
    const below = rect.bottom + 220 < viewBottom();
    return panel.kind === "react" ? { left: Math.min(Math.max(rect.left + rect.width / 2, STRIP_HALF), window.innerWidth - STRIP_HALF), top: rect.top - 6, "--bt-origin": "bottom center" } : { left: Math.min(rect.left, window.innerWidth - 208), ...below ? { top: rect.bottom + 4 } : { bottom: viewBottom() - rect.top + 4, "--bt-origin": "bottom left" } };
  }, [panel, tick]);
  const copy2 = () => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1e3);
    });
  };
  const download2 = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: `${name}-message.md` });
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1e3);
  };
  const item = (label, Icon, run2) => (0, import_react31.createElement)("button", { key: label, type: "button", role: "menuitem", onClick: () => {
    close();
    run2();
  } }, (0, import_react31.createElement)(Icon), label);
  return (0, import_react31.createElement)(
    "div",
    { ref: tools, className: "bt-tools", "data-open": panel !== null || tapped || void 0 },
    react ? (0, import_react31.createElement)("button", { type: "button", className: "bt-tool", "aria-label": t("Add reaction"), title: t("Add reaction"), "aria-expanded": panel?.kind === "react", onClick: (event) => open("react", event) }, (0, import_react31.createElement)(SmileIcon)) : null,
    sessionId ? (0, import_react31.createElement)("button", { type: "button", className: "bt-tool", "aria-label": t("Reply"), title: t("Reply"), onClick: () => actions.quote(sessionId, text) }, (0, import_react31.createElement)(ReplyIcon)) : null,
    (0, import_react31.createElement)("button", { type: "button", className: "bt-tool", "aria-label": t("More message actions"), title: t("More"), "aria-haspopup": "menu", "aria-expanded": panel?.kind === "more", onClick: (event) => open("more", event) }, copied ? (0, import_react31.createElement)(CheckIcon) : (0, import_react31.createElement)(DotsIcon)),
    panel?.kind === "react" ? (0, import_react_dom3.createPortal)((0, import_react31.createElement)(
      "div",
      { ref: pop, className: "bt-react-strip", role: "menu", "aria-label": t("Reactions"), style: place },
      REACTIONS.map((emoji) => (0, import_react31.createElement)("button", { key: emoji, type: "button", role: "menuitem", "aria-label": emoji, onClick: () => {
        close();
        react(emoji);
      } }, emoji))
    ), document.body) : null,
    panel?.kind === "more" ? (0, import_react_dom3.createPortal)((0, import_react31.createElement)(
      "div",
      { ref: pop, className: "bt-menu", role: "menu", "aria-label": t("Message actions"), style: place },
      item(t("Copy"), CopyIcon, copy2),
      item(t("Download"), DownloadIcon, download2)
    ), document.body) : null
  );
}
function GroupMessage({ bot, text, texts: texts2 = [text], room: room2, roster, actions, msgKey, useUi, whole, time, duration }) {
  const ref = (0, import_react31.useRef)(null);
  (0, import_react31.useLayoutEffect)(() => {
    const el = ref.current;
    if (!el?.closest) return void 0;
    const flow = el.closest("[data-chat-flow]");
    if (!flow) return void 0;
    scheduleGroupChains(flow);
    return () => scheduleGroupChains(flow);
  }, [bot.id]);
  const lead = (0, import_react31.createElement)(
    "button",
    { type: "button", className: "bt-lead", "aria-label": t("Open {name}'s chat", { name: bot.name }), onClick: () => actions.openSession(bot.id) },
    (0, import_react31.createElement)(BotMark, { bot, size: 22 })
  );
  const flat = layoutOf(roster.prefs) === "flat";
  const took = Number.isFinite(duration) && duration >= 1e3 ? elapsedLabel(duration) : void 0;
  return (0, import_react31.createElement)(
    "div",
    { ref, className: "bt-group-msg", "data-bot-id": bot.id },
    (0, import_react31.createElement)(
      "span",
      { className: "bt-group-name", style: flat ? void 0 : { color: inkText(colorOf(bot)) } },
      flat ? lead : null,
      bot.name,
      room2?.admin === bot.id ? (0, import_react31.createElement)("span", { className: "bt-group-role" }, t("Admin")) : null,
      Number.isFinite(time) ? (0, import_react31.createElement)("span", { className: "bt-group-time", title: clockLabel(time) }, messageClock(time)) : null,
      took ? (0, import_react31.createElement)("span", { className: "bt-group-took", title: t("Ran for {duration}", { duration: took }) }, took) : null
    ),
    (0, import_react31.createElement)(Bubbles, { texts: texts2, roster, selfId: bot.id, actions, sessionId: room2?.id, msgKey, useUi, lead: flat ? null : lead, whole })
  );
}
