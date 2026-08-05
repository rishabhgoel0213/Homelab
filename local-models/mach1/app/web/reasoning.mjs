const THINKING_END = "</think>";

function markerSuffixLength(text, marker) {
  const limit = Math.min(text.length, marker.length - 1);
  for (let length = limit; length > 0; length--) {
    if (marker.startsWith(text.slice(-length))) return length;
  }
  return 0;
}

export function splitReasoningOutput(text, enabled) {
  const value = String(text ?? "");
  if (!enabled) return { reasoning: null, content: value };
  const boundary = value.indexOf(THINKING_END);
  if (boundary < 0) return { reasoning: value, content: "" };
  return {
    reasoning: value.slice(0, boundary),
    content: value.slice(boundary + THINKING_END.length),
  };
}

export function createReasoningStream(enabled, onChunk) {
  let channel = enabled ? "reasoning" : "content";
  let pending = "";

  const emit = (kind, text) => {
    if (text) onChunk({ channel: kind, piece: text });
  };

  return {
    push(piece) {
      if (!piece) return;
      if (channel === "content") return emit("content", piece);
      pending += piece;
      const boundary = pending.indexOf(THINKING_END);
      if (boundary >= 0) {
        emit("reasoning", pending.slice(0, boundary));
        pending = pending.slice(boundary + THINKING_END.length);
        channel = "content";
        emit("content", pending);
        pending = "";
        return;
      }
      const retained = markerSuffixLength(pending, THINKING_END);
      const safeLength = pending.length - retained;
      emit("reasoning", pending.slice(0, safeLength));
      pending = pending.slice(safeLength);
    },
    finish() {
      emit(channel, pending);
      pending = "";
    },
  };
}
