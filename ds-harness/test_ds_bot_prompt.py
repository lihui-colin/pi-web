"""Compatibility regression: old assemblies include tools; new ones do not."""
import subprocess
import unittest
from patches.ds_bot_prompt import OLD, patch


class PromptPatchTests(unittest.TestCase):
    def test_old_and_new_assembly_contracts(self):
        callback = """async function filter(next) {
          const assembled = await next();
          return {
            ...assembled,
""" + OLD + """
            sections: assembled.sections.filter(section => !HIDDEN_SECTIONS.has(section.name)),
          };
        }"""
        script = """
import assert from 'node:assert/strict';
const HIDDEN_TOOLS = ['subagent'];
const HIDDEN_SECTIONS = new Set(['tool:subagent']);
""" + patch(callback) + """
const base = {sections: [{name:'persona'}, {name:'tool:subagent'}], contexts: [], variables: {a:1}};
const modern = await filter(async () => base);
assert.equal('tools' in modern, false);
assert.deepEqual(modern.sections, [{name:'persona'}]);
assert.equal(modern.contexts, base.contexts);
assert.equal(modern.variables, base.variables);
const legacy = await filter(async () => ({...base, tools:[{name:'subagent'}, {name:'bash'}]}));
assert.deepEqual(legacy.tools, [{name:'bash'}]);
assert.equal(base.sections.length, 2);
"""
        subprocess.run(['node', '--input-type=module', '-e', script], check=True)

    def test_idempotent_and_rejects_unknown(self):
        fixed = patch(OLD)
        self.assertEqual(patch(fixed), fixed)
        with self.assertRaises(ValueError):
            patch('unknown source')


if __name__ == '__main__':
    unittest.main()
