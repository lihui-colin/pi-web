// Execute the patched publication excerpts with a small React hook harness.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const state = [], copied = [], downloads = [], quotes = [], reactions = [], opened = [];
let hook = 0;
const h = (type, props, ...children) => ({type, props: props ?? {}, children});
const context = {
  import_react31: {createElement: h, useState: initial => {
    const index = hook++;
    if (!(index in state)) state[index] = initial;
    return [state[index], value => { state[index] = value; }];
  }, useRef: () => ({current: null}), useMemo: fn => fn(), useLayoutEffect: () => {}},
  import_react_dom3: {createPortal: element => element},
  t: text => text, useViewport: () => 0, useDismiss: () => {},
  window: {innerWidth: 390}, viewBottom: () => 800, STRIP_HALF: 115,
  navigator: {clipboard: {writeText: async text => { copied.push(text); }}},
  Blob, URL: {createObjectURL: () => 'blob:test', revokeObjectURL: () => {}},
  setTimeout: () => {},
  document: {body: {}, createElement: () => {
    const link = {click: () => downloads.push([link.href, link.download])};
    return link;
  }},
  SmileIcon: 'smile', ReplyIcon: 'reply', CopyIcon: 'copy', DownloadIcon: 'download', CheckIcon: 'check',
  REACTIONS: ['👍', '❤️'], BotMark: 'mark', Bubbles: 'bubbles',
  layoutOf: prefs => prefs.layout, inkText: x => x, colorOf: () => 'blue',
  clockLabel: () => 'clock', messageClock: () => 'time', elapsedLabel: () => '1s',
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(0, 'utf8'), context);
const actions = {quote: (...args) => quotes.push(args), openSession: id => opened.push(id)};
const render = () => {
  hook = 0;
  return context.MessageTools({text: 'reply text', name: 'Chief', sessionId: 'room',
    react: value => reactions.push(value), actions});
};
async function check() {
  let tree = render();
  const button = label => tree.children.find(x => x?.props['aria-label'] === label);
  button('Copy').props.onClick();
  await Promise.resolve();
  tree = render();
  assert.equal(button('Copied').children[0].type, 'check');
  assert.deepEqual(copied, ['reply text']);
  button('Download').props.onClick();
  assert.deepEqual(downloads, [['blob:test', 'Chief-message.md']]);
  button('Reply').props.onClick();
  assert.deepEqual(quotes, [['room', 'reply text']]);
  assert.equal(button('More message actions'), undefined);
  button('Add reaction').props.onClick({currentTarget: {
    getBoundingClientRect: () => ({left: 360, top: 500, width: 44}),
  }});
  tree = render();
  const strip = tree.children.find(x => x?.props.className === 'bt-react-strip');
  assert.equal(strip.props.style.left, 275); // Popover stays inside a narrow viewport.
  strip.children[0][0].props.onClick();
  assert.deepEqual(reactions, ['👍']);
  assert.equal(render().props['data-open'], undefined);

  for (const layout of ['flat', 'bubble']) {
    const group = context.GroupMessage({bot: {id: 'chief', name: 'Chief'}, text: 'hello',
      room: {id: 'room'}, roster: {prefs: {layout}}, actions, time: 1, duration: 1000});
    const [metadata, bubbles] = group.children;
    const avatar = metadata.children.find(x => x?.props?.className === 'bt-lead');
    assert.ok(avatar);
    assert.equal(bubbles.props.lead, undefined); // One avatar outside the bubble in both layouts.
    assert.equal(metadata.children[metadata.children.indexOf(avatar) + 1].props.className, 'bt-group-time');
    avatar.props.onClick();
  }
  assert.deepEqual(opened, ['chief', 'chief']);
}
check().catch(error => { console.error(error); process.exitCode = 1; });
