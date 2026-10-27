const test = require('node:test');
const assert = require('node:assert/strict');
const { labReaPlan } = require('../web/lab-rea.js');

test('lab sem aplicativo não pode ser analisado por RE', () => {
  const plan = labReaPlan({ id: 'a', package_id: '' }, { currentId: 'a' });
  assert.equal(plan.allowed, false);
  assert.match(plan.reason, /aplicativo/i);
});

test('lab sem package_id definido também é bloqueado', () => {
  const plan = labReaPlan({ id: 'a' }, { currentId: 'a' });
  assert.equal(plan.allowed, false);
});

test('lab atual é analisado no lugar, sem retomar', () => {
  const plan = labReaPlan({ id: 'a', package_id: 'com.exemplo.app' }, { currentId: 'a' });
  assert.equal(plan.allowed, true);
  assert.equal(plan.isCurrent, true);
  assert.equal(plan.needsResume, false);
  assert.equal(plan.package, 'com.exemplo.app');
});

test('lab não-atual precisa ser retomado antes de analisar', () => {
  const plan = labReaPlan({ id: 'b', package_id: 'com.exemplo.outro' }, { currentId: 'a' });
  assert.equal(plan.allowed, true);
  assert.equal(plan.isCurrent, false);
  assert.equal(plan.needsResume, true);
  assert.equal(plan.package, 'com.exemplo.outro');
});

test('sem lab retorna bloqueio seguro', () => {
  const plan = labReaPlan(null, { currentId: 'a' });
  assert.equal(plan.allowed, false);
});
