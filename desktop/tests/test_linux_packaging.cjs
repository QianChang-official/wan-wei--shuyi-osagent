'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const PACKAGING_DIR = path.join(__dirname, '..', 'packaging', 'linux');
const packageJson = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'),
);
const linuxPackWorkflow = fs.readFileSync(
  path.join(__dirname, '..', '..', '.github', 'workflows', 'desktop-linux-pack.yml'),
  'utf8',
);
const postinst = fs.readFileSync(path.join(PACKAGING_DIR, 'postinst.sh'), 'utf8');
const postrm = fs.readFileSync(path.join(PACKAGING_DIR, 'postrm.sh'), 'utf8');
const lifecycleTest = fs.readFileSync(
  path.join(__dirname, 'test_linux_packaging_lifecycle.sh'),
  'utf8',
);

test('desktop package includes the Arena report consumed by the overview', () => {
  assert.ok(
    packageJson.build.extraResources.some((resource) =>
      resource.from === '../reports/production_memory_eval_metrics.json'
      && resource.to === 'reports/production_memory_eval_metrics.json'),
  );
  assert.equal(
    (linuxPackWorkflow.match(/memory_arena\/metrics_contract\.py/g) || []).length,
    2,
    'deb and rpm payloads must both pass the shared Arena contract',
  );
});

test('postinst fails closed when the Electron sandbox cannot be secured', () => {
  assert.match(postinst, /if \[ ! -f "\$SANDBOX" \]; then/);
  assert.match(postinst, /chown root:root "\$SANDBOX"\nchmod 4755 "\$SANDBOX"/);

  const sandboxSection = postinst.slice(
    postinst.indexOf('SANDBOX='),
    postinst.indexOf('SERVICE_SRC='),
  );
  assert.doesNotMatch(sandboxSection, /\|\| true/);
});

test('maintenance scripts safely manage the command-line launcher', () => {
  assert.match(
    postinst,
    /COMMAND_TARGET="\/opt\/wanwei-shuyi-desktop\/wanwei-shuyi-desktop"/,
  );
  assert.match(postinst, /elif \[ -e "\$COMMAND_LINK" \]; then/);
  assert.match(postinst, /ln -s "\$COMMAND_TARGET" "\$COMMAND_LINK"/);
  assert.match(
    postrm,
    /\[ "\$\(readlink "\$COMMAND_LINK"\)" = "\$COMMAND_TARGET" \]/,
  );
  assert.match(postrm, /rm -f "\$COMMAND_LINK"/);
  assert.match(postrm, /find "\$APP_DIR" -depth -type d -empty -delete/);
  assert.match(postrm, /! find "\$APP_DIR" -mindepth 1 ! -type d/);
});

test('CI executes isolated safety cases and real deb/rpm upgrade lifecycles', () => {
  assert.match(lifecycleTest, /WANWEI_PACKAGING_TEST_CONTAINER/);
  assert.match(lifecycleTest, /sh "\$POSTRM" upgrade/);
  assert.match(lifecycleTest, /sh "\$POSTRM" 1/);
  assert.match(lifecycleTest, /wanwei-foreign-command/);
  assert.match(linuxPackWorkflow, /sh \/test-lifecycle\.sh/);
  assert.match(linuxPackWorkflow, /sudo dpkg -i "\$deb"/);
  assert.match(linuxPackWorkflow, /rpm -Uvh --replacepkgs --nodeps/);
  assert.match(linuxPackWorkflow, /rpm -e --nodeps wanwei-shuyi-desktop/);
});

test('postrm removes the copied user service only on final uninstall', () => {
  assert.match(postrm, /remove\|purge\|disappear\|0\|""/);
  assert.match(postrm, /rm -f \/etc\/systemd\/user\/wanwei-shuyi-desktop\.service/);
  assert.doesNotMatch(postrm, /upgrade\|1/);
});
