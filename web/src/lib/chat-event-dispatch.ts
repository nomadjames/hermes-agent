import { titleFromSessionInfoPayload } from "./chat-title";

interface ChatEventHandlers {
  onDashboardNewSessionRequest?: () => void;
  onMessageComplete?: () => void;
  onSessionTitleChange?: (title: string | null) => void;
}

export function dispatchChatEvent(
  type: string | undefined,
  payload: unknown,
  handlers: ChatEventHandlers,
): void {
  if (type === "session.info") {
    const title = titleFromSessionInfoPayload(payload);
    if (title !== undefined) {
      handlers.onSessionTitleChange?.(title);
    }
  } else if (type === "dashboard.new_session_requested") {
    handlers.onDashboardNewSessionRequest?.();
  } else if (type === "message.complete") {
    handlers.onMessageComplete?.();
  }
}
