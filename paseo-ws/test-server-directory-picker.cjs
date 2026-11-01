// Run with PASEO_PLAYWRIGHT_MODULE pointing to an installed Playwright module if needed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
let chromium;
try { ({ chromium } = require(process.env.PASEO_PLAYWRIGHT_MODULE || 'playwright')); } catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
}

test('server directory picker: lazy tree, selection, navigation, errors, cancellation and mobile layout', { skip: !chromium && 'Install Playwright or set PASEO_PLAYWRIGHT_MODULE to run browser tests' }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1100, height: 850 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport });
      await page.setContent('<button id="opener">Open picker</button>');
      await page.addScriptTag({ path: path.join(__dirname, 'server-directory-picker.js') });
      await page.evaluate(() => {
        window.calls = []; window.failPrivate = true;
        window.testClient = { async listDirectory(cwd, relative) {
          calls.push({ cwd, relative });
          if (cwd === '/private' && failPrivate) throw Error('denied');
          const names = { '/': ['home', 'private', 'empty', '<img onerror=alert(1)>'], '/home': ['alice'], '/home/alice': ['project with spaces'], '/home/alice/project with spaces': [], '/private': ['allowed'], '/empty': [] }[cwd] || [];
          return { entries: [...names.map(name => ({ name, kind: 'directory' })), { name: 'file.txt', kind: 'file' }] };
        }};
        window.openTest = initialPath => {
          document.getElementById('opener').focus(); window.result = 'pending';
          window.__paseoPickServerDirectory(testClient, { initialPath, hostLabel: '<host>' }).then(value => window.result = value);
        };
        openTest('/');
      });
      await page.getByRole('treeitem', { name: 'home', exact: true }).waitFor();
      assert.equal(await page.locator('.dp-host').textContent(), 'Folders on <host>');
      assert.equal(await page.locator('dialog img').count(), 0);
      assert.equal(await page.getByText('file.txt', { exact: true }).count(), 0);
      assert.equal(await page.evaluate(() => calls.length), 1, 'collapsed folders do not load recursively');
      await page.getByRole('tree').getByRole('button', { name: 'home', exact: true }).click();
      await page.getByRole('treeitem', { name: 'alice', exact: true }).waitFor();
      assert.equal(await page.locator('.dp-selected').textContent(), '/home');
      await page.getByRole('tree').getByRole('button', { name: 'home', exact: true }).click();
      assert.equal(await page.getByRole('treeitem', { name: 'alice', exact: true }).isVisible(), true);
      assert.equal(await page.evaluate(() => calls.filter(call => call.cwd === '/home').length), 1);
      await page.getByRole('button', { name: 'alice', exact: true }).click();
      const project = page.getByRole('treeitem', { name: 'project with spaces', exact: true });
      await project.getByRole('button', { name: 'project with spaces', exact: true }).click();
      assert.equal(await page.evaluate(() => result), 'pending', 'selection does not open a project until confirmation');
      assert.equal(await page.locator('.dp-selected').textContent(), '/home/alice/project with spaces');
      const bounds = await page.locator('dialog').boundingBox();
      assert.ok((await page.locator('.dp-tree').boundingBox()).height > 200, 'folder tree retains useful browsing space');
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= viewport.width && bounds.y + bounds.height <= viewport.height);
      await page.getByRole('button', { name: 'Select this folder', exact: true }).click();
      assert.equal(await page.evaluate(() => result), '/home/alice/project with spaces');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'opener');
      await page.evaluate(() => openTest('/home/alice'));
      await page.getByRole('treeitem', { name: 'project with spaces', exact: true }).waitFor();
      await page.getByRole('tree').getByRole('button', { name: 'project with spaces', exact: true }).click();
      await page.getByRole('button', { name: '↑ Parent folder', exact: true }).click();
      assert.equal(await page.locator('.dp-selected').textContent(), '/home/alice');
      await page.getByRole('button', { name: '↑ Parent folder', exact: true }).click();
      await page.getByRole('treeitem', { name: 'alice', exact: true }).waitFor();
      assert.equal(await page.locator('.dp-selected').textContent(), '/home');
      await page.keyboard.press('Escape');
      assert.equal(await page.evaluate(() => result), null);
      await page.evaluate(() => openTest('/private'));
      await page.getByRole('alert').waitFor();
      assert.equal(await page.getByRole('button', { name: 'Select this folder', exact: true }).isDisabled(), true);
      await page.evaluate(() => window.failPrivate = false);
      await page.getByRole('button', { name: 'Retry', exact: true }).click();
      await page.getByRole('treeitem', { name: 'allowed', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      await page.evaluate(() => openTest('/empty'));
      await page.getByText('No subfolders', { exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Select this folder', exact: true }).isEnabled(), true);
      await page.keyboard.press('Escape');
      await page.evaluate(() => openTest('/'));
      await page.getByRole('treeitem', { name: 'empty', exact: true }).waitFor();
      await page.getByRole('treeitem', { name: 'empty', exact: true }).focus();
      await page.keyboard.press('ArrowRight');
      await page.getByText('No subfolders', { exact: true }).waitFor();
      await page.keyboard.press('ArrowRight');
      assert.equal(await page.evaluate(() => document.activeElement.dataset.path), '/empty');
      await page.keyboard.press('Escape');
      await page.evaluate(() => {
        const fastList = testClient.listDirectory;
        testClient.listDirectory = (cwd, relative) => cwd === '/home' ? new Promise(resolve => window.finishHome = resolve) : fastList(cwd, relative);
        openTest('/');
      });
      await page.getByRole('treeitem', { name: 'home', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Expand /home', exact: true }).click();
      await page.locator('.dp-cancel').first().focus();
      await page.evaluate(() => finishHome({ entries: [{ name: 'alice', kind: 'directory' }] }));
      await page.getByRole('treeitem', { name: 'alice', exact: true }).waitFor();
      assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('.dp-cancel')), true);
      await page.keyboard.press('Escape');
      // A request completing after dismissal must not resurrect the dialog.
      await page.evaluate(() => {
        testClient.listDirectory = () => new Promise(resolve => window.finishRequest = resolve);
        openTest('/');
      });
      await page.getByText('Loading folders…', { exact: true }).waitFor();
      await page.keyboard.press('Escape');
      await page.evaluate(() => finishRequest({ entries: [{ name: 'late', kind: 'directory' }] }));
      assert.equal(await page.locator('dialog').count(), 0);
      await page.close();
    }
  } finally { await browser.close(); }
});
