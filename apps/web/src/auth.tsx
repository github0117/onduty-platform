import { Button, Result, Spin } from "antd";
import { UserManager } from "oidc-client-ts";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

const authMode = import.meta.env.VITE_AUTH_MODE ?? "dev";
const identityStorageKey = "digital-workforce:test-identity";
const identitySwitchNoticeStorageKey =
  "digital-workforce:identity-switch-notice";
const businessUnitStorageKey = "digital-workforce:test-business-unit";
const oidcBusinessUnitStorageKey = "digital-workforce:oidc-business-unit";
const defaultBusinessUnit = "bu_demo";

export interface TestIdentityProfile {
  id: string;
  label: string;
  description: string;
  actorId: string;
  role: string;
  landingPath: string;
}

export const testIdentityProfiles: TestIdentityProfile[] = [
  {
    id: "service-agent",
    label: "客服坐席",
    description: "处理客户服务和接管会话",
    actorId: "demo.agent",
    role: "agent",
    landingPath: "/customer-service/workbench",
  },
  {
    id: "service-supervisor",
    label: "客服主管",
    description: "查看运营指标并处理写操作审批",
    actorId: "demo.supervisor",
    role: "supervisor",
    landingPath: "/customer-service/admin",
  },
  {
    id: "knowledge-operator",
    label: "知识运营",
    description: "维护知识、评测和修复任务",
    actorId: "demo.knowledge_operator",
    role: "knowledge_operator",
    landingPath: "/knowledge/documents",
  },
  {
    id: "business-manager",
    label: "业务经理",
    description: "查看业务效果和运行审计",
    actorId: "demo.business_manager",
    role: "business_manager",
    landingPath: "/operations",
  },
  {
    id: "platform-admin",
    label: "平台管理员",
    description: "配置员工、模型、连接器和治理规则",
    actorId: "demo.admin",
    role: "admin",
    landingPath: "/employees/roster",
  },
];

export const testBusinessUnits = [
  { value: "bu_demo", label: "主要演示单元" },
  { value: "bu_acceptance", label: "隔离验真单元" },
];

export function isTestIdentityMode(): boolean {
  return authMode !== "oidc";
}

export function getActiveTestIdentity(): TestIdentityProfile {
  if (typeof window === "undefined") return testIdentityProfiles[4];
  const stored = window.localStorage.getItem(identityStorageKey);
  return (
    testIdentityProfiles.find((profile) => profile.id === stored) ??
    testIdentityProfiles[4]
  );
}

export function getActiveBusinessUnitId(): string {
  if (typeof window === "undefined") return defaultBusinessUnit;
  if (authMode === "oidc") {
    return (
      window.sessionStorage.getItem(oidcBusinessUnitStorageKey) ??
      import.meta.env.VITE_OIDC_BUSINESS_UNIT_ID ??
      defaultBusinessUnit
    );
  }
  const stored = window.localStorage.getItem(businessUnitStorageKey);
  return testBusinessUnits.some((unit) => unit.value === stored)
    ? stored!
    : defaultBusinessUnit;
}

export function switchTestIdentity(profileId: string): string {
  const profile =
    testIdentityProfiles.find((item) => item.id === profileId) ??
    testIdentityProfiles[4];
  window.localStorage.setItem(identityStorageKey, profile.id);
  window.sessionStorage.setItem(
    identitySwitchNoticeStorageKey,
    profile.label,
  );
  return profile.landingPath;
}

export function consumeIdentitySwitchNotice(): string | null {
  if (typeof window === "undefined") return null;
  const label = window.sessionStorage.getItem(
    identitySwitchNoticeStorageKey,
  );
  window.sessionStorage.removeItem(identitySwitchNoticeStorageKey);
  return label;
}

export function switchTestBusinessUnit(businessUnitId: string): void {
  const value = testBusinessUnits.some((unit) => unit.value === businessUnitId)
    ? businessUnitId
    : defaultBusinessUnit;
  window.localStorage.setItem(businessUnitStorageKey, value);
}

const oidcSettings = {
  authority: import.meta.env.VITE_OIDC_ISSUER ?? "",
  client_id: import.meta.env.VITE_OIDC_CLIENT_ID ?? "",
  redirect_uri:
    import.meta.env.VITE_OIDC_REDIRECT_URI ??
    (typeof window === "undefined" ? "" : window.location.origin),
  response_type: "code",
  scope: import.meta.env.VITE_OIDC_SCOPE ?? "openid profile email",
  automaticSilentRenew: false,
};

let userManager: UserManager | null = null;

function getManager(): UserManager {
  if (authMode !== "oidc") {
    throw new Error("OIDC manager is unavailable in dev auth mode");
  }
  if (!oidcSettings.authority || !oidcSettings.client_id) {
    throw new Error("VITE_OIDC_ISSUER and VITE_OIDC_CLIENT_ID are required");
  }
  userManager ??= new UserManager(oidcSettings);
  return userManager;
}

export async function login(): Promise<void> {
  await getManager().signinRedirect();
}

export async function initializeAuth(): Promise<void> {
  if (authMode !== "oidc") {
    return;
  }

  const manager = getManager();
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") && params.has("state")) {
    await manager.signinRedirectCallback();
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  const user = await manager.getUser();
  if (!user || user.expired) {
    await manager.signinRedirect();
    return;
  }
  const payload = decodeJwtPayload(user.access_token);
  const businessUnits = payload?.business_units;
  const businessUnit =
    Array.isArray(businessUnits) && typeof businessUnits[0] === "string"
      ? businessUnits[0]
      : typeof payload?.business_unit_id === "string"
        ? payload.business_unit_id
        : import.meta.env.VITE_OIDC_BUSINESS_UNIT_ID;
  if (typeof businessUnit === "string" && businessUnit) {
    window.sessionStorage.setItem(
      oidcBusinessUnitStorageKey,
      businessUnit,
    );
  }
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const normalized = payload
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(payload.length / 4) * 4, "=");
    return JSON.parse(window.atob(normalized)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export async function getAuthHeaders(): Promise<Record<string, string>> {
  if (authMode !== "oidc") {
    const identity = getActiveTestIdentity();
    return {
      "X-Actor-Id": identity.actorId,
      "X-Actor-Role": identity.role,
      "X-Business-Unit-Id": getActiveBusinessUnitId(),
    };
  }

  const user = await getManager().getUser();
  if (!user || user.expired || !user.access_token) {
    await getManager().signinRedirect();
    throw new Error("登录已失效，请重新登录");
  }
  return {
    Authorization: `Bearer ${user.access_token}`,
  };
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const isOidc = useMemo(() => authMode === "oidc", []);

  useEffect(() => {
    let active = true;
    initializeAuth()
      .then(() => {
        if (active) setState("ready");
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "身份验证失败");
        setState("error");
      });
    return () => {
      active = false;
    };
  }, []);

  if (state === "loading") {
    return (
      <div className="auth-screen">
        <Spin size="large" />
        <span>{isOidc ? "正在验证企业身份…" : "正在启动工作台…"}</span>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="auth-screen">
        <Result
          status="error"
          title="无法完成身份验证"
          subTitle={error}
          extra={
            isOidc ? (
              <Button type="primary" onClick={() => login().catch(() => undefined)}>
                重新登录
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  }

  return <>{children}</>;
}

