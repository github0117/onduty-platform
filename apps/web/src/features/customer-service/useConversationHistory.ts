import { useRef, useState } from "react";

import type { ConversationTurn, HistoryScope } from "./model";

export interface UseConversationHistoryOptions {
  initialHistory: ConversationTurn[];
}

export function useConversationHistory({
  initialHistory,
}: UseConversationHistoryOptions) {
  const [historyScope, setHistoryScope] = useState<HistoryScope>("current");
  const [followLatest, setFollowLatest] = useState(true);
  const historyContainerRef = useRef<HTMLDivElement>(null);
  const [scrollToTicketOnLoad, setScrollToTicketOnLoad] = useState(false);
  const [history, setHistory] = useState<ConversationTurn[]>(initialHistory);

  return {
    historyScope,
    setHistoryScope,
    followLatest,
    setFollowLatest,
    historyContainerRef,
    scrollToTicketOnLoad,
    setScrollToTicketOnLoad,
    history,
    setHistory,
  };
}
