import { Alert, Space } from "antd";
import { useEffect, useState } from "react";

type FeedbackLevel = "success" | "info" | "warning" | "error";

type FeedbackItem = {
  id: number;
  level: FeedbackLevel;
  content: string;
};

const feedbackEventName = "digital-workforce:feedback";
let nextFeedbackId = 1;

function show(level: FeedbackLevel, content: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<FeedbackItem>(feedbackEventName, {
      detail: {
        id: nextFeedbackId++,
        level,
        content,
      },
    }),
  );
}

export const message = {
  success: (content: string) => show("success", content),
  info: (content: string) => show("info", content),
  warning: (content: string) => show("warning", content),
  error: (content: string) => show("error", content),
};

export function ActionFeedback() {
  const [items, setItems] = useState<FeedbackItem[]>([]);

  useEffect(() => {
    const receive = (event: Event) => {
      const item = (event as CustomEvent<FeedbackItem>).detail;
      setItems((current) =>
        [
          item,
          ...current.filter((entry) => entry.content !== item.content),
        ].slice(0, 3),
      );
    };
    window.addEventListener(feedbackEventName, receive);
    return () => window.removeEventListener(feedbackEventName, receive);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="action-feedback" aria-live="polite">
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        {items.map((item) => (
          <Alert
            key={item.id}
            type={item.level}
            showIcon
            closable
            message={item.content}
            onClose={() =>
              setItems((current) =>
                current.filter((entry) => entry.id !== item.id),
              )
            }
          />
        ))}
      </Space>
    </div>
  );
}
