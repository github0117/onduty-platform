import { Button, Result, Space, Tag, Typography } from "antd";

import type { Capability } from "./capabilities";
import { capabilityLabels } from "./capabilities";

const { Text } = Typography;

export default function AccessDenied({
  roleLabel,
  capabilities,
  onBackHome,
}: {
  roleLabel: string;
  capabilities: ReadonlySet<string>;
  onBackHome: () => void;
}) {
  return (
    <Result
      status="403"
      title="当前身份无权访问此页面"
      subTitle={
        <Space direction="vertical" size="small">
          <Text>当前角色：{roleLabel}</Text>
          <Text type="secondary">
            页面和按钮与服务端权限使用同一份能力清单，因此不会显示“可见但不可用”的操作。
          </Text>
          <Space wrap>
            {[...capabilities].slice(0, 8).map((capability) => (
              <Tag key={capability}>
                {capabilityLabels[capability as Capability] ?? capability}
              </Tag>
            ))}
          </Space>
        </Space>
      }
      extra={
        <Button type="primary" onClick={onBackHome}>
          回到我的首页
        </Button>
      }
    />
  );
}
