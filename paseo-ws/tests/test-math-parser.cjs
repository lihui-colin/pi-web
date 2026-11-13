const { test } = require('node:test');
const assert = require('node:assert/strict');
const { upstreamParser, nodes, text, math } = require('./markdown-parser-fixture.cjs');
const options = { latexMath: true, hardSoftBreaks: true };
const f = String.raw`\[E=mc^2\]`;
const inline = String.raw`\(\alpha + \beta\)`;

for (const [name, input, expected] of [
  ['display algebra', f, ['E=mc^2']],
  ['inline algebra', String.raw`\(E=mc^2\)`, ['E=mc^2']],
  ['single variable', String.raw`\(x\)`, ['x']],
  ['single command', String.raw`\(\alpha\)`, [String.raw`\alpha`]],
  ['unknown commands reach renderer', String.raw`\[\custom{x}\]`, [String.raw`\custom{x}`]],
  ['subscripts', String.raw`\[a_{ij}^{2}\]`, ['a_{ij}^{2}']],
  ['explicit delimiters define math regardless of words', String.raw`\[src/foo.js\]`, ['src/foo.js']],
  ['adjacent inline formulas', String.raw`\(a+b\)\(c+d\)`, ['a+b', 'c+d']],
  ['separated inline formulas', String.raw`\(a+b\) and \(c+d\)`, ['a+b', 'c+d']],
  ['mixed dollar and bracket formulas', String.raw`$x$ and \(y\)`, ['x', 'y']],
  ['math in link label', String.raw`[\(x\)](https://example.test)`, ['x']],
  ['math in table cell', '| a | b |\n|---|---|\n| ' + inline + ' | c |', [String.raw`\alpha + \beta`]],
  ['quoted display formula', '> \\[\n> x^2\n> \\]', ['\nx^2\n']],
  ['list display formula', '- \\[\n  x^2\n  \\]', ['\nx^2\n']],
  ['CRLF display formula', '\\[\r\nx^2\r\n\\]', ['\r\nx^2\r\n']],
  ['escaped closer in body', String.raw`\(x \\) + y\)`, [String.raw`x \\) + y`]],
  ['literal backticks inside formula', String.raw`\(\text{a` + '`' + String.raw`b} + x\)`, ['\\text{a`b} + x']],
  ['literal dollar inside bracket math', String.raw`\(\text{cost \$5} + x\)`, [String.raw`\text{cost \$5} + x`]],
  ['slot-like source text cannot collide', 'PASEOMATHSLOT0END ' + inline, [String.raw`\alpha + \beta`]],
  ['long formula', '\\(' + 'x+'.repeat(2001) + '1\\)', ['x+'.repeat(2001) + '1']],
]) {
  test(`math recognition: ${name}`, async t => {
    const p = upstreamParser(t, true); if (!p) return;
    assert.deepEqual(math(await p.parseMarkdown(input, options)), expected);
  });
}

for (const [name, input] of [
  ['plain Markdown', '# heading\n\n**bold** and _italic_\n\n- [x] task\n- item'],
  ['inline code', '`' + f + '`'],
  ['multiline inline code', '`first\n' + f + '\nlast`\nafter'],
  ['double backtick code', '``first `\n' + f + '\nlast``\nafter'],
  ['indented code continuation', '    first\n    ' + f + '\n'],
  ['tab indented code', '\tfirst\n\t' + f + '\n'],
  ['CRLF indented code', 'intro\r\n\r\n    ' + f + '\r\n'],
  ['space-only blank line before code', 'intro\n  \n    ' + f + '\n'],
  ['code after heading', '# heading\n    ' + f],
  ['code after thematic break', '---\n    ' + f],
  ['top-level fence', '~~~latex\n' + f + '\n~~~'],
  ['top-level CRLF fence', '```latex\r\n' + f + '\r\n```'],
  ['unclosed fence', '~~~\n' + f],
  ['quoted fence', '> ~~~\n> ' + f + '\n> ~~~'],
  ['list fence', '- ```latex\n  ' + f + '\n  ```'],
  ['quote inside list fence', '- > ~~~\n  > ' + f + '\n  > ~~~'],
  ['quote inside ordered list fence', '1. > ~~~\n   > ' + f + '\n   > ~~~'],
  ['list inside quote fence', '> - ~~~\n>   ' + f + '\n>   ~~~'],
  ['literal quotes inside code', '~~~\n> ' + f + '\n' + f + '\n~~~'],
  ['link destination', String.raw`[go](https://example.test/\(a+b\))`],
  ['link title', String.raw`[go](https://example.test "\(a+b\)")`],
  ['reference destination', '[go][id]\n\n[id]: https://example.test/\\(a+b\\)'],
  ['image destination', String.raw`![plot](https://example.test/\(a+b\).png)`],
  ['raw HTML code', '<pre>' + f + '</pre>'],
  ['existing dollar math', String.raw`$$\text{\(\alpha + \beta\)}$$`],
  ['escaped delimiter', String.raw`\\(a+b\\)`],
  ['unclosed formula', String.raw`\(a+b`],
  ['mismatched formula', String.raw`\(a+b\]`],
  ['formula cannot cross blank paragraph', '\\(x\n\ny\\)'],
  ['formula cannot close inside code', '\\(x\n\n    \\)'],
]) {
  test(`preserve upstream AST: ${name}`, async t => {
    const original = upstreamParser(t); if (!original) return;
    const patched = upstreamParser(t, true);
    assert.equal(JSON.stringify(await patched.parseMarkdown(input, options)),
      JSON.stringify(await original.parseMarkdown(input, options)));
  });
}

test('display math is a block, adjacent inline math remains separate', async t => {
  const p = upstreamParser(t, true); if (!p) return;
  const ast = await p.parseMarkdown(f, options);
  assert.equal(ast.children[0].type, 'LatexMathDisplay');
  const adjacent = await p.parseMarkdown(String.raw`\(x\)\(y\)`, options);
  assert.equal(nodes(adjacent, 'LatexMathInline').length, 2);
});

test('code protection does not suppress the following formula', async t => {
  const p = upstreamParser(t, true); if (!p) return;
  for (const code of ['- > ~~~\n  > ' + f + '\n  > ~~~', '    ' + f, '`first\n' + f + '\nlast`']) {
    const ast = await p.parseMarkdown(code + '\n\n' + f, options);
    assert.deepEqual(math(ast), ['E=mc^2']);
  }
});

test('streaming prefixes and completed formulas use the same parser', async t => {
  const p = upstreamParser(t, true); if (!p) return;
  for (let i = 0; i < f.length; i++) assert.deepEqual(math(await p.parseMarkdown(f.slice(0, i), options)), []);
  assert.deepEqual(math(await p.parseMarkdown(f, options)), ['E=mc^2']);
  assert.deepEqual(math(await p.parseMarkdown(String.raw`\(x\) then \(y`, options)), ['x']);
});

test('disabled math and synchronous parsing retain their contracts', async t => {
  const original = upstreamParser(t); if (!original) return;
  const p = upstreamParser(t, true);
  const disabled = { ...options, latexMath: false };
  assert.equal(JSON.stringify(await p.parseMarkdown(f, disabled)), JSON.stringify(await original.parseMarkdown(f, disabled)));
  const ast = await p.parseMarkdown(f, options);
  assert.equal(JSON.stringify(p.parseMarkdownSync(f, options)), JSON.stringify(ast));
});

test('formula placeholders preserve surrounding emphasis punctuation', async t => {
  const p = upstreamParser(t, true); if (!p) return;
  const ast = await p.parseMarkdown(String.raw`a\(x\)_b_`, options);
  assert.deepEqual(math(ast), ['x']);
  assert.equal(nodes(ast, 'Emphasis').map(text).join(''), 'b');
});

test('entity-encoded source cannot impersonate a formula slot', async t => {
  const p = upstreamParser(t, true); if (!p) return;
  const source = '&#xfffc;&#80;ASEOMATHSLOT0END&#xfffc; ' + String.raw`\(x\)`;
  const ast = await p.parseMarkdown(source, options);
  assert.deepEqual(math(ast), ['x']);
  const original = upstreamParser(t);
  const prefix = await original.parseMarkdown('&#xfffc;&#80;ASEOMATHSLOT0END&#xfffc;', options);
  assert.equal(text(ast), text(prefix) + ' x');
});

test('Markdown features survive math recognition in the same message', async t => {
  const p = upstreamParser(t, true); if (!p) return;
  const original = upstreamParser(t);
  for (const prose of [
    '# heading\n\n**bold** and _italic_\n\n- [x] task\n- item',
    '| a | b |\n|---|---|\n| 1 | 2 |',
    '> [!NOTE]\n> note text',
    '```mermaid\ngraph TD; A-->B;\n```',
    '[link](https://example.test) and ![image](https://example.test/a.png)',
  ]) {
    const before = await original.parseMarkdown(prose, options);
    const after = await p.parseMarkdown(prose + '\n\n' + f, options);
    assert.equal(after.children.at(-1).type, 'LatexMathDisplay');
    after.children.pop();
    assert.equal(JSON.stringify(after), JSON.stringify(before));
  }
});
