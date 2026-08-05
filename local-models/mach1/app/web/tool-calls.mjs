const TOOL_BLOCK = /<tool>\s*([\s\S]*?)\s*<\/tool>/g;
const NAMED_TOOL_BLOCK = /^\s*<([A-Za-z_][A-Za-z0-9_.-]*)>\s*([\s\S]*?)\s*<\/(?:tool|[A-Za-z_][A-Za-z0-9_.-]*)>\s*$/;
const SHORTHAND_TOOL = /^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\n([\s\S]*?)\s*$/;
const SHORTHAND_ARGUMENT = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/;

function normalizeArguments(value) {
  if (value == null) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value;
  if (typeof value === "string") {
    const parsed = JSON.parse(value);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  }
  throw new Error("tool arguments must be a JSON object");
}

function makeToolCall(name, args, makeId) {
  return {
    id: makeId(),
    type: "function",
    function: {
      name,
      arguments: JSON.stringify(normalizeArguments(args)),
    },
  };
}

function parseShorthand(text, allowedToolNames) {
  const match = String(text ?? "").match(SHORTHAND_TOOL);
  if (!match || !allowedToolNames.has(match[1])) return null;
  const args = {};
  for (const line of match[2].split("\n")) {
    const assignment = line.trim().match(SHORTHAND_ARGUMENT);
    if (!assignment) return null;
    let value;
    try {
      value = JSON.parse(assignment[2]);
    } catch {
      if (assignment[2].startsWith("'") && assignment[2].endsWith("'")) {
        value = assignment[2].slice(1, -1);
      } else {
        return null;
      }
    }
    args[assignment[1]] = value;
  }
  return { name: match[1], arguments: args };
}

function parseNamedBlock(text, allowedToolNames) {
  const match = String(text ?? "").match(NAMED_TOOL_BLOCK);
  if (!match || !allowedToolNames.has(match[1])) return null;
  try {
    return { name: match[1], arguments: normalizeArguments(JSON.parse(match[2])) };
  } catch {
    return null;
  }
}

export function parseToolOutput(
  text,
  makeId = () => `call_${crypto.randomUUID().replaceAll("-", "")}`,
  allowedToolNames = [],
) {
  const toolCalls = [];
  const errors = [];
  const content = String(text ?? "").replace(TOOL_BLOCK, (_block, payload) => {
    try {
      const parsed = JSON.parse(payload);
      if (!parsed || typeof parsed.name !== "string" || !parsed.name) {
        throw new Error("tool name is missing");
      }
      toolCalls.push(makeToolCall(parsed.name, parsed.arguments, makeId));
      return "";
    } catch (error) {
      errors.push(String(error.message ?? error));
      return _block;
    }
  }).trim();
  if (!toolCalls.length) {
    const allowed = new Set(allowedToolNames);
    const alternate = parseNamedBlock(content, allowed) ?? parseShorthand(content, allowed);
    if (alternate) {
      toolCalls.push(makeToolCall(alternate.name, alternate.arguments, makeId));
      return { content: null, toolCalls, errors };
    }
  }
  return { content: content || null, toolCalls, errors };
}

export function renderAssistantToolCalls(toolCalls) {
  if (!Array.isArray(toolCalls)) return "";
  return toolCalls.flatMap((toolCall) => {
    const fn = toolCall?.function;
    if (!fn || typeof fn.name !== "string") return [];
    let args = fn.arguments ?? {};
    if (typeof args === "string") {
      try { args = JSON.parse(args); } catch { args = {}; }
    }
    return [`<tool>\n${JSON.stringify({ name: fn.name, arguments: args })}\n</tool>`];
  }).join("\n");
}
