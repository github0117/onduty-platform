import type { DigitalEmployee } from "./types";

export const workflowLabels: Record<string, string> = {
  customer_service_ticket_v1: "客服工单处理",
  hr_onboarding_document_collection_v1: "HR 入职资料收集",
};

export const domainLabels: Record<string, string> = {
  customer_service: "客户服务",
  human_resources: "人力资源",
  finance: "财务",
  ecommerce_operations: "电商运营",
  content_media: "内容制作",
};

export const templateLabels: Record<string, string> = {
  ecommerce_presales: "电商售前客服",
  ecommerce_aftersales: "电商售后客服",
  ecommerce_logistics: "物流查询客服",
  ecommerce_listing_operator: "商品上架数字员工",
  ecommerce_visual_creator: "视觉内容数字员工",
  ecommerce_operations_supervisor: "电商运营主管数字员工",
  hr_onboarding: "HR 入职专员",
};

export const entryRoleLabels: Record<string, string> = {
  PRIMARY: "默认员工",
  SPECIALIST: "专业员工",
  FALLBACK: "兜底员工",
};

export function employeeReadiness(employee: DigitalEmployee): {
  label: string;
  color: string;
  detail: string;
} {
  if (employee.status === "DISABLED") {
    return {
      label: "已停用",
      color: "default",
      detail: "不会参与自动派单；重新启用前需要再次检查。",
    };
  }
  if (employee.status === "TRIAL") {
    return {
      label: "待上岗检查",
      color: "orange",
      detail: "先补齐知识、规程和工具，再点击“评估并激活”。",
    };
  }
  if (employee.status === "EVALUATION_FAILED") {
    const failed = employee.activation_evaluation.checks?.find(
      (check) => check.status === "FAILED",
    );
    return {
      label: "检查未通过",
      color: "red",
      detail: failed?.detail ?? "请补齐缺失资源后重新检查。",
    };
  }
  if (employee.activation_evaluation.passed === true) {
    return {
      label: "可以上岗",
      color: "green",
      detail: "最近一次能力检查已通过。",
    };
  }
  return {
    label: "已启用",
    color: "cyan",
    detail: "尚未执行完整上岗检查，建议先做一次能力评估。",
  };
}
