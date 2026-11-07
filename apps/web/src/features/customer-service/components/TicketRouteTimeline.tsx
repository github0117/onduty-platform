import { Timeline } from "antd";

import type { TicketDetail } from "../../../types";
import {
  groundingStatusLabels,
  humanReasonLabels,
  localizedLabel,
} from "../../../statusLabels";
import { categoryLabels } from "../model";

interface TicketRouteTimelineProps {
  ticket: TicketDetail;
}

export function TicketRouteTimeline({ ticket }: TicketRouteTimelineProps) {
  return (
    <Timeline
      style={{ marginTop: 24 }}
      items={[
        { color: "blue", children: "买家已提交问题" },
        {
          color: "blue",
          children: ticket.classification
            ? `分类完成：${
                categoryLabels[ticket.classification.primary] ??
                ticket.classification.primary
              }`
            : "正在分类",
        },
        {
          color: ticket.draft ? "green" : ticket.needs_human ? "orange" : "gray",
          children: ticket.draft
            ? `回答草稿已生成 · ${localizedLabel(
                groundingStatusLabels,
                ticket.draft.grounding_status,
              )}`
            : ticket.needs_human
              ? `已转人工：${localizedLabel(
                  humanReasonLabels,
                  ticket.routing.human_reason,
                  "需要人工处理",
                )}`
              : "正在检索知识",
        },
      ]}
    />
  );
}
