import assert from "node:assert/strict";
import { parseToolOutput, renderAssistantToolCalls } from "../app/web/tool-calls.mjs";

const parsed = parseToolOutput(
  'Before\n<tool>\n{"name":"bash","arguments":{"command":"pwd"}}\n</tool>\nAfter',
  () => "call_test",
);
assert.equal(parsed.content, "Before\n\nAfter");
assert.deepEqual(parsed.toolCalls, [{
  id: "call_test",
  type: "function",
  function: { name: "bash", arguments: '{"command":"pwd"}' },
}]);
assert.deepEqual(parsed.errors, []);

assert.equal(
  renderAssistantToolCalls(parsed.toolCalls),
  '<tool>\n{"name":"bash","arguments":{"command":"pwd"}}\n</tool>',
);

const malformed = parseToolOutput("<tool>not json</tool>");
assert.equal(malformed.content, "<tool>not json</tool>");
assert.equal(malformed.toolCalls.length, 0);
assert.equal(malformed.errors.length, 1);

const shorthand = parseToolOutput(
  'bash\ncommand="pwd"',
  () => "call_shorthand",
  ["bash"],
);
assert.equal(shorthand.content, null);
assert.deepEqual(shorthand.toolCalls, [{
  id: "call_shorthand",
  type: "function",
  function: { name: "bash", arguments: '{"command":"pwd"}' },
}]);

const prose = parseToolOutput('bash\ncommand="pwd"');
assert.equal(prose.content, 'bash\ncommand="pwd"');
assert.equal(prose.toolCalls.length, 0);

const namedBlock = parseToolOutput(
  '<bash>\n{"command":"pwd"}\n</tool>',
  () => "call_named",
  ["bash"],
);
assert.equal(namedBlock.content, null);
assert.deepEqual(namedBlock.toolCalls, [{
  id: "call_named",
  type: "function",
  function: { name: "bash", arguments: '{"command":"pwd"}' },
}]);
