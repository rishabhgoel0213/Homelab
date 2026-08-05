import assert from "node:assert/strict";
import { createReasoningStream, splitReasoningOutput } from "../app/web/reasoning.mjs";

assert.deepEqual(splitReasoningOutput("answer", false), {
  reasoning: null,
  content: "answer",
});
assert.deepEqual(splitReasoningOutput("work</think>\nanswer", true), {
  reasoning: "work",
  content: "\nanswer",
});

const chunks = [];
const stream = createReasoningStream(true, (chunk) => chunks.push(chunk));
for (const piece of ["work</th", "ink>\nans", "wer"]) stream.push(piece);
stream.finish();
assert.deepEqual(chunks, [
  { channel: "reasoning", piece: "work" },
  { channel: "content", piece: "\nans" },
  { channel: "content", piece: "wer" },
]);

const plain = [];
const plainStream = createReasoningStream(false, (chunk) => plain.push(chunk));
plainStream.push("answer");
plainStream.finish();
assert.deepEqual(plain, [{ channel: "content", piece: "answer" }]);
