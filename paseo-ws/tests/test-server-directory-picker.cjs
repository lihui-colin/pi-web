const { sourceFile } = require('./support.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
let chromium;
try { ({ chromium } = require(process.env.PASEO_PLAYWRIGHT_MODULE || 'playwright')); } catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
}

async function setup(browser, viewport) {
  const page = await browser.newPage({ viewport });
  await page.setContent('<button id="opener">Open picker</button>');
  await page.addScriptTag({ path: sourceFile('server-directory-picker.js') });
  await page.evaluate(() => {
    window.calls = []; window.creates = []; window.failPrivate = true;
    window.names = { '/': ['home', 'private', 'empty', '<img onerror=alert(1)>'], '/home': ['alice', 'bob'], '/home/alice': ['project with spaces', '.hidden', 'project2'], '/home/alice/project with spaces': ['src'], '/private': ['allowed'], '/empty': [] };
    window.testClient = {
      async listDirectory(cwd, relative) {
        calls.push({ cwd, relative });
        if (cwd === '/private' && failPrivate) throw Error('denied');
        if (!(cwd in names)) throw Error('missing');
        return { entries: [...names[cwd].map(name => ({ name, kind: 'directory' })), { name: 'file.txt', kind: 'file' }] };
      },
      async createFileEntry(input) {
        creates.push(input);
        if (input.name === 'denied') return { success: false, error: 'Permission denied' };
        names[input.cwd].push(input.name);
        names[(input.cwd === '/' ? '' : input.cwd) + '/' + input.name] = [];
        return { success: true, path: input.name };
      }
    };
    window.openTest = initialPath => {
      document.getElementById('opener').focus(); window.result = 'pending';
      window.__paseoPickServerDirectory(testClient, { initialPath, hostLabel: '<host>' }).then(value => window.result = value);
    };
  });
  return page;
}
const row = (page, name) => page.locator('.dp-columns').getByRole('button', { name, exact: true });
const crumb = (page, name) => page.getByRole('navigation', { name: 'Folder path' }).getByRole('button', { name, exact: true });
async function ready(page) { await page.getByRole('button', { name: 'Open', exact: true }).waitFor(); await page.waitForFunction(() => !document.querySelector('.dp-confirm').disabled); }

test('DSH-style browser replaces tree: Miller columns, crumbs, hidden folders, path editing, creation and mobile layout', { skip: !chromium && 'Install Playwright or set PASEO_PLAYWRIGHT_MODULE' }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1100, height: 850 }, { width: 390, height: 844 }]) {
      const page = await setup(browser, viewport);
      await page.evaluate(() => openTest('/'));
      await ready(page);
      assert.equal(await page.getByRole('tree').count(), 0);
      assert.equal(await page.locator('.dp-host').textContent(), 'Folders on <host>');
      assert.equal(await page.locator('dialog img').count(), 0);
      assert.equal(await page.getByText('file.txt', { exact: true }).count(), 0);
      assert.equal(await page.locator('.dp-column').count(), 1);
      assert.equal(await page.evaluate(() => calls.length), 1);
      await row(page, 'home').click();
      await row(page, 'alice').waitFor();
      assert.equal(await page.locator('.dp-column').count(), 2);
      assert.equal(await page.locator('.dp-row[data-path="/home"]').getAttribute('aria-current'), 'true');
      await row(page, 'alice').click();
      await row(page, 'project with spaces').waitFor();
      assert.equal(await page.locator('.dp-column').count(), 2, 'right-pane pick advances one level');
      assert.equal(await row(page, 'home').count(), 0);
      assert.equal(await row(page, '.hidden').count(), 0);
      await page.getByRole('button', { name: 'Show hidden files' }).click();
      await row(page, '.hidden').waitFor();
      assert.equal(await page.locator('.dp-hidden').getAttribute('aria-pressed'), 'true');
      await page.getByRole('button', { name: 'Show hidden files' }).click();
      await row(page, 'project with spaces').click();
      await row(page, 'src').waitFor();
      assert.equal(await page.evaluate(() => result), 'pending');
      const bounds = await page.locator('dialog').boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= viewport.width && bounds.y >= 0 && bounds.y + bounds.height <= viewport.height);
      assert.ok((await page.locator('.dp-columns').boundingBox()).height > 200);
      assert.equal(await page.locator('dialog').evaluate(el => el.scrollWidth <= el.clientWidth), true);
      await page.getByRole('button', { name: 'Open', exact: true }).click();
      assert.equal(await page.evaluate(() => result), '/home/alice/project with spaces');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'opener');

      await page.evaluate(() => openTest('/home/alice'));
      await ready(page);
      await crumb(page, 'home').click();
      await row(page, 'alice').waitFor();
      await ready(page);
      assert.equal(await page.locator('.dp-column').count(), 2, 'crumb navigation preserves parent and target panes');
      await page.getByRole('button', { name: 'Edit path' }).click();
      const input = page.getByRole('textbox', { name: 'Folder path', exact: true });
      await input.fill('/home/alice/pro');
      await page.waitForFunction(() => document.querySelector('.dp-column:last-child')?.getAttribute('aria-label') === '/home/alice');
      await row(page, 'project2').waitFor();
      assert.equal(await row(page, '.hidden').count(), 0);
      await input.fill('/home/alice/.h');
      await row(page, '.hidden').waitFor();
      assert.equal(await row(page, 'project2').count(), 0);
      await input.fill('/home/alice/no-match');
      await row(page, 'project2').waitFor();
      await input.fill('/home/alice/../alice/project with spaces');
      await input.press('Enter');
      await row(page, 'src').waitFor();
      await ready(page);
      await page.getByRole('button', { name: 'Edit path' }).click();
      await input.fill('/missing');
      await input.press('Enter');
      await page.locator('.dp-error').waitFor({ state: 'visible' });
      assert.equal(await row(page, 'src').isVisible(), true, 'failed path keeps readable panes');
      await input.press('Escape');
      assert.equal(await page.locator('dialog').count(), 1, 'Escape leaves path editor before dismissing picker');
      await page.keyboard.press('Escape');
      assert.equal(await page.evaluate(() => result), null);

      await page.evaluate(() => openTest('/private'));
      await page.locator('.dp-error').waitFor({ state: 'visible' });
      assert.equal(await page.locator('.dp-confirm').isDisabled(), true);
      await page.evaluate(() => window.failPrivate = false);
      await page.getByRole('button', { name: 'Edit path' }).click();
      await page.getByRole('textbox', { name: 'Folder path', exact: true }).fill('/private');
      await page.keyboard.press('Enter');
      await row(page, 'allowed').waitFor();
      await ready(page);
      await page.getByRole('button', { name: 'New folder', exact: true }).click();
      await page.getByRole('textbox', { name: 'Folder name' }).fill('../bad');
      await page.getByRole('button', { name: 'Create', exact: true }).click();
      assert.equal(await page.evaluate(() => creates.length), 0);
      await page.getByRole('textbox', { name: 'Folder name' }).fill('denied');
      await page.getByRole('button', { name: 'Create', exact: true }).click();
      await page.getByText('Permission denied', { exact: true }).waitFor();
      await page.getByRole('textbox', { name: 'Folder name' }).fill('new folder');
      await page.keyboard.press('Enter');
      await page.locator('.dp-create').waitFor({ state: 'hidden' });
      await ready(page);
      assert.deepEqual(await page.evaluate(() => creates.at(-1)), { cwd: '/private', parentPath: '.', name: 'new folder', kind: 'directory' });
      await page.getByRole('button', { name: 'Open', exact: true }).click();
      assert.equal(await page.evaluate(() => result), '/private/new folder');
      await page.evaluate(() => openTest('/empty'));
      await page.getByText('No subfolders', { exact: true }).waitFor();
      await ready(page);
      await page.keyboard.press('Escape');
      await page.close();
    }
  } finally { await browser.close(); }
});

test('folder browser ignores superseded responses and preserves focus, cancellation and keyboard navigation', { skip: !chromium && 'Install Playwright or set PASEO_PLAYWRIGHT_MODULE' }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, { width: 1100, height: 850 });
    await page.evaluate(() => {
      const fast = testClient.listDirectory;
      testClient.listDirectory = (cwd, path) => cwd === '/home' ? new Promise(resolve => window.finishHome = resolve) : fast(cwd, path);
      openTest('/');
    });
    await ready(page);
    await row(page, 'home').click();
    assert.equal(await page.locator('.dp-confirm').isDisabled(), true, 'cannot confirm unverified folder');
    await row(page, 'empty').click();
    await ready(page);
    await page.evaluate(() => finishHome({ entries: [{ name: 'late', kind: 'directory' }] }));
    assert.equal(await row(page, 'late').count(), 0);
    assert.equal(await row(page, 'empty').getAttribute('aria-current'), 'true');
    await row(page, 'home').click();
    await page.locator('.dp-cancel').focus();
    await page.evaluate(() => finishHome({ entries: [{ name: 'alice', kind: 'directory' }] }));
    await row(page, 'alice').waitFor();
    assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('.dp-cancel')), true, 'completed listing does not steal footer focus');
    await row(page, 'private').focus();
    await page.keyboard.press('Home');
    assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('.dp-row')), true);
    await page.keyboard.press('End');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.path), '/private');
    await page.keyboard.press('Escape');
    await page.evaluate(() => {
      testClient.listDirectory = () => new Promise(resolve => window.finishRequest = resolve);
      openTest('/');
    });
    await page.locator('.dp-loading').waitFor({ state: 'visible' });
    await page.keyboard.press('Escape');
    await page.evaluate(() => finishRequest({ entries: [{ name: 'late', kind: 'directory' }] }));
    assert.equal(await page.locator('dialog').count(), 0);
    await page.close();
  } finally { await browser.close(); }
});

test('mobile uses one full-width column, reachable touch actions and parent navigation', { skip: !chromium && 'Install Playwright or set PASEO_PLAYWRIGHT_MODULE' }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{width:320,height:640}, {width:390,height:844}, {width:568,height:320}]) {
      const page = await setup(browser, viewport);
      await page.evaluate(() => openTest('/home/alice'));
      await ready(page);
      assert.equal(await page.locator('.dp-column:visible').count(), 1);
      assert.equal(await page.locator('.dp-columns').evaluate(el => el.scrollWidth <= el.clientWidth), true);
      const rowBounds = await row(page, 'project with spaces').boundingBox();
      assert.ok(rowBounds.height >= 44 && rowBounds.width > viewport.width - 70);
      for (const selector of ['.dp-new', '.dp-cancel', '.dp-confirm', '.dp-up']) {
        const bounds = await page.locator(selector).boundingBox();
        assert.ok(bounds.height >= 44 && bounds.x >= 0 && bounds.x + bounds.width <= viewport.width && bounds.y + bounds.height <= viewport.height);
      }
      await page.getByRole('button', {name:'↑ Parent folder', exact:true}).click();
      await row(page, 'alice').waitFor();
      await ready(page);
      await page.locator('.dp-confirm').click();
      assert.equal(await page.evaluate(() => result), '/home');
      await page.evaluate(() => openTest('/home/alice'));
      await ready(page);
      await page.setViewportSize({width:1100,height:850});
      assert.equal(await page.locator('.dp-column:visible').count(), 2, 'desktop restores both columns');
      await page.close();
    }
  } finally { await browser.close(); }
});
