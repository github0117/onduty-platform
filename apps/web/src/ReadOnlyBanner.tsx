import { Alert } from "antd";

export default function ReadOnlyBanner({
  title = "当前角色为只读访问",
  description,
}: {
  title?: string;
  description: string;
}) {
  return (
    <Alert
      type="info"
      showIcon
      message={title}
      description={description}
    />
  );
}
