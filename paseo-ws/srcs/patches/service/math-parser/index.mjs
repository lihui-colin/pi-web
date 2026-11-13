import { fromMarkdown } from 'mdast-util-from-markdown';
import { math } from 'micromark-extension-math';
import { mathFromMarkdown } from 'mdast-util-math';
import { gfm } from 'micromark-extension-gfm';
import { gfmFromMarkdown } from 'mdast-util-gfm';

// A micromark inline construct runs inside Markdown's grammar, before escapes.
// Code, HTML and link destinations are consumed by their own constructs.
function tokenizeBrackets(effects, ok, nok) {
  let close, slash;
  return start;
  function start(code) {
    effects.enter('mathText');
    effects.enter('mathTextSequence');
    effects.consume(code);
    return opening;
  }
  function opening(code) {
    if (code !== 40 && code !== 91) return nok(code);
    close = code === 40 ? 41 : 93;
    effects.consume(code);
    effects.exit('mathTextSequence');
    return body;
  }
  function body(code) {
    if (code === null) return nok(code);
    if (code === 92) {
      slash = effects.enter('mathTextData');
      effects.consume(code);
      return afterSlash;
    }
    const type = code < -2 ? 'lineEnding' : 'mathTextData';
    effects.enter(type); effects.consume(code); effects.exit(type);
    return body;
  }
  function afterSlash(code) {
    if (code === close) {
      slash.type = 'mathTextSequence';
      effects.consume(code);
      effects.exit('mathTextSequence');
      effects.exit('mathText');
      return ok;
    }
    // Consume an escaped character together with its backslash, so a second
    // backslash cannot open a closing delimiter.
    if (code === null || code < -2) {
      effects.exit('mathTextData');
      return body(code);
    }
    effects.consume(code);
    effects.exit('mathTextData');
    return body;
  }
}
const brackets = { text: { 92: { name: 'latexBrackets', tokenize: tokenizeBrackets } } };

function recognize(source) {
  const tree = fromMarkdown(source, {
    extensions: [gfm(), math(), brackets],
    mdastExtensions: [gfmFromMarkdown(), mathFromMarkdown()],
  });
  const regions = [];
  function visit(node) {
    if (node.type === 'inlineMath' || node.type === 'math') {
      const start = node.position.start.offset, end = node.position.end.offset;
      const raw = source.slice(start, end);
      // micromark accepts unclosed dollar flow fences. Keep streaming input raw
      // until its closing fence arrives, matching the existing chat behavior.
      if (node.type === 'math' && !/\n[ \t>]*\${2,}[ \t]*$/.test(raw)) return;
      regions.push({ start, end, value: node.value,
        display: node.type === 'math' || raw.startsWith('$$') || raw.startsWith('\\[') });
      return;
    }
    for (const child of node.children || []) visit(child);
  }
  visit(tree);
  return regions;
}

const separator = node => node.type === 'SoftBreak' || node.type === 'LineBreak'
  || (node.type === 'Text' && !node.content.trim());
// Preserve Enriched Markdown's display-math paragraph promotion convention.
function promote(node) {
  if (node.type !== 'Paragraph' || !node.children) return [node];
  const children = node.children;
  const isolated = i => children[i].type === 'LatexMathDisplay'
    && (i === 0 || i === children.length - 1 || separator(children[i - 1]) || separator(children[i + 1]));
  if (!children.some((_, i) => isolated(i))) return [node];
  const out = [];
  let run = [];
  function flush() {
    while (run.length && separator(run[0])) run.shift();
    while (run.length && separator(run[run.length - 1])) run.pop();
    if (run.length) out.push({ ...node, children: run });
    run = [];
  }
  children.forEach((child, i) => {
    if (isolated(i)) { flush(); out.push(child); } else run.push(child);
  });
  flush();
  return out;
}

export function parseMarkdownMath(source, parseOriginal, enabled = true) {
  // Dollar-only messages retain the exact upstream parsing path.
  if (!enabled || !/\\[([]/.test(source)) return parseOriginal(source);
  const regions = recognize(source);
  if (!regions.length) return parseOriginal(source);
  // Opaque, collision-free text slots carry positions through the original
  // parser. Formula bodies never become Markdown source or dollar delimiters.
  let prefix = 'PASEOMATHSLOT';
  // Entity decoding can create text not literally present in the source.
  const decoded = source.includes('&') ? JSON.stringify(parseOriginal(source)) : '';
  while (source.includes(prefix) || decoded.includes(prefix)) prefix += 'X';
  const slots = new Map();
  let masked = '', last = 0;
  regions.forEach((region, i) => {
    const key = '\uFFFC' + prefix + i + 'END\uFFFC';
    slots.set(key, { type: region.display ? 'LatexMathDisplay' : 'LatexMathInline',
      children: [{ type: 'Text', content: region.value }] });
    masked += source.slice(last, region.start) + key;
    last = region.end;
  });
  masked += source.slice(last);
  const ast = parseOriginal(masked);
  if (!ast) return ast;
  const pattern = new RegExp('(\uFFFC' + prefix + '[0-9]+END\uFFFC)', 'g');
  function restore(node) {
    if (node.type === 'Text' && node.content) {
      return node.content.split(pattern).filter(Boolean)
        .map(part => slots.get(part) ?? { ...node, content: part });
    }
    if (node.children) node.children = node.children.flatMap(restore);
    return promote(node);
  }
  return restore(ast)[0];
}

globalThis.paseoParseMarkdownMath = parseMarkdownMath;
