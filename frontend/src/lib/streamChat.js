export async function streamChat(path, body, onEvent, signal) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "답변을 받지 못했습니다. 다시 시도해주세요.",
    );
  }
  if (
    !response.body ||
    !response.headers.get("content-type")?.includes("text/event-stream")
  ) {
    throw new Error("답변 수신이 중단되었습니다. 다시 시도해주세요.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const lines = frame.split("\n");
        const event = lines
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const raw = lines
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!event || !raw) continue;
        const data = JSON.parse(raw);
        if (event === "error")
          throw new Error(
            data.detail || "답변을 받지 못했습니다. 다시 시도해주세요.",
          );
        if (event === "done") {
          if (typeof data.turn?.answer?.text !== "string")
            throw new Error("답변 수신이 중단되었습니다. 다시 시도해주세요.");
          return data;
        }
        onEvent(event, data);
      }
      if (done)
        throw new Error("답변 수신이 중단되었습니다. 다시 시도해주세요.");
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
