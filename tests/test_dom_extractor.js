// Run with: node tests/test_dom_extractor.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = { window: {}, console };
vm.runInNewContext(fs.readFileSync('extension/dom_extractor.js', 'utf8'), context);
const label = context.window.AIOverlayDOMExtractor.extractElementText;

const input = {
  tagName: 'INPUT',
  value: '',
  placeholder: '',
  labels: [{ innerText: 'Repository name *' }],
  getAttribute: () => null,
};
assert.equal(label(input), 'Repository name *');
input.value = 'bench-demo';
assert.equal(label(input), 'Repository name *: bench-demo');

const readmeSwitch = {
  tagName: 'BUTTON',
  innerText: '',
  textContent: '',
  parentElement: { innerText: 'Off' },
  getAttribute: () => null,
};
assert.equal(label(readmeSwitch), 'Off');

const visibilityPicker = {
  tagName: 'BUTTON',
  innerText: 'Public',
  getAttribute: (name) => name === 'aria-haspopup' ? 'dialog' : null,
};
assert.equal(label(visibilityPicker), 'Public (opens menu)');

const unassociatedInput = {
  ...input,
  value: '',
  labels: [],
  parentElement: { querySelector: () => ({ innerText: 'Repository name *' }), parentElement: null },
};
assert.equal(label(unassociatedInput), 'Repository name *');
console.log('DOM extractor accessible-label tests passed');
