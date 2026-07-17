import { describe, expect, it, vi } from "vitest";

import { dispatchChatEvent } from "./chat-event-dispatch";
import {
  ptyAttachTokenStorageKey,
  shouldResetPtyBeforeReplay,
} from "./pty-reconnect";

describe("chat response visibility", () => {
  it("notifies the terminal when an assistant response completes", () => {
    const onMessageComplete = vi.fn();

    dispatchChatEvent("message.complete", { text: "done" }, {
      onMessageComplete,
    });

    expect(onMessageComplete).toHaveBeenCalledOnce();
  });

  it("resets an existing terminal before reconnect replay", () => {
    expect(shouldResetPtyBeforeReplay("reconnecting", 1)).toBe(true);
    expect(shouldResetPtyBeforeReplay("open", 1)).toBe(true);
    expect(shouldResetPtyBeforeReplay("connecting", 0)).toBe(false);
  });

  it("does not reattach a resumed session to another session's renderer", () => {
    const current = ptyAttachTokenStorageKey("boddicker\0current-session");
    const resumed = ptyAttachTokenStorageKey("boddicker\0resumed-session");

    expect(current).not.toBe(resumed);
  });
});
