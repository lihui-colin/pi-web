"""Current DSH prompt waterfall does not own the provider tool list."""
import test_support  # Configure the service source import path.
import subprocess
import unittest
from patches.plugins.ds_bot.ds_bot_apply import PROMPT_OLD as OLD, PROMPT_APPLIED_026, patch_prompt as patch


class PromptPatchTests(unittest.TestCase):
    def test_current_assembly_contract(self):
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
assert.equal(base.sections.length, 2);
"""
        subprocess.run(['node', '--input-type=module', '-e', script], check=True)

    def test_idempotent_and_rejects_unknown(self):
        fixed = patch(OLD)
        self.assertEqual(patch(fixed), fixed)
        with self.assertRaises(ValueError):
            patch('unknown source')

    def test_existing_026_patch_converges_to_current_host_only(self):
        self.assertEqual(patch(PROMPT_APPLIED_026), patch(OLD))


if __name__ == '__main__':
    unittest.main()
