import { Button, Result, Spin } from "antd";
import type { Capability } from "./capabilities";
import { canAccessPath as canAccessCapabilityPath } from "./capabilities";
import { UserManager } from "oidc-client-ts";
import type { ReactNode } from "react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

const authMode = import.meta.env.VITE_AUTH_MODE ?? "dev";
const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
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
    id: "auditor",
    label: "审计员",
    description: "只读查看审批、事故与运行记录",
    actorId: "demo.auditor",
    role: "auditor",
    landingPath: "/operations",
  },
  {
    id: "platform-admin",
    label: "平台管理员",
    description: "配置员工、模型、连接器和治理规则",
    actorId: "demo.admin",
    role: "admin",
    landingPath: "/overview",
  },
];

export const testBusinessUnits = [
  { value: "bu_demo", label: "演示租户（固定数据）" },
  { value: "bu_acceptance", label: "隔离验真租户（无演示数据）" },
];

export function isTestIdentityMode(): boolean {
  return authMode !== "oidc";
}

/**
 * Return the stored dev profile, or ``null`` in OIDC mode.
 *
 * OIDC identities must never fall back to a local profile: the authoritative
 * role comes from ``GET /api/v1/me`` only.
 */
export function getStoredTestProfile(): TestIdentityProfile | null {
  if (authMode === "oidc" || typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(identityStorageKey);
  return (
    testIdentityProfiles.find((profile) => profile.id === stored) ??
    testIdentityProfiles[testIdentityProfiles.length - 1]
  );
}

function readStoredBusinessUnit(): string | null {
  if (typeof window === "undefined") return null;
  if (authMode === "oidc") {
    return window.sessionStorage.getItem(oidcBusinessUnitStorageKey);
  }
  return window.localStorage.getItem(businessUnitStorageKey);
}

function writeStoredBusinessUnit(businessUnitId: string): void {
  if (typeof window === "undefined") return;
  if (authMode === "oidc") {
    window.sessionStorage.setItem(oidcBusinessUnitStorageKey, businessUnitId);
    return;
  }
  window.localStorage.setItem(businessUnitStorageKey, businessUnitId);
}

function clearStoredBusinessUnit(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(businessUnitStorageKey);
  window.sessionStorage.removeItem(oidcBusinessUnitStorageKey);
}

let activeBusinessUnitInMemory: string | null = null;

export function getActiveBusinessUnitId(): string {
  if (activeBusinessUnitInMemory) return activeBusinessUnitInMemory;
  if (typeof window === "undefined") return defaultBusinessUnit;
  if (authMode === "oidc") {
    return (
      readStoredBusinessUnit() ??
      import.meta.env.VITE_OIDC_BUSINESS_UNIT_ID ??
      defaultBusinessUnit
    );
  }
  const stored = readStoredBusinessUnit();
  return testBusinessUnits.some((unit) => unit.value === stored)
    ? stored!
    : defaultBusinessUnit;
}

function setActiveBusinessUnitInMemory(businessUnitId: string): void {
  activeBusinessUnitInMemory = businessUnitId;
}

export function switchTestIdentity(profileId: string): string {
  const profile = testIdentityProfiles.find((item) => item.id === profileId);
  if (!profile) {
    throw new Error(`Unknown test identity: ${profileId}`);
  }
  if (authMode === "oidc") {
    throw new Error("Test identities are unavailable in OIDC mode");
  }
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

export interface DemoResetFeature {
  enabled: boolean;
  business_unit_id: string;
  active_business_unit_eligible: boolean;
  reason: string | null;
}

export interface AuthSnapshot {
  actor_id: string;
  role: string;
  role_label: string;
  issuer: string;
  auth_mode: string;
  service_identity: string | false;
  policy_version: string;
  test_identity_switch_enabled: boolean;
  business_units: string[];
  business_unit_labels: Record<string, string>;
  primary_business_unit_id: string;
  active_business_unit_id: string;
  capabilities: Capability[];
  features: {
    demo_reset: DemoResetFeature;
  };
}

export class AuthRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null,
  ) {
    super(message);
    this.name = "AuthRequestError";
  }
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
  }
}

export async function getAuthHeaders(): Promise<Record<string, string>> {
  if (authMode !== "oidc") {
    const identity = getStoredTestProfile();
    if (!identity) {
      throw new Error("测试身份不可用，请刷新页面重试");
    }
    return {
      "X-Actor-Id": identity.actorId,
      "X-Actor-Role": identity.role,
      "X-Business-Unit-Id": getActiveBusinessUnitId(),
      "X-Business-Units": testBusinessUnits
        .map((unit) => unit.value)
        .join(","),
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

async function requestMe(businessUnitId?: string): Promise<AuthSnapshot> {
  const headers = await getAuthHeaders();
  const query = businessUnitId
    ? `?business_unit_id=${encodeURIComponent(businessUnitId)}`
    : "";
  const response = await fetch(`${apiBase}/api/v1/me${query}`, {
    headers,
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as
      | { detail?: string; code?: string; title?: string }
      | null;
    if (response.status === 401 && authMode === "oidc") {
      await login();
    }
    throw new AuthRequestError(
      problem?.detail ?? problem?.title ?? "无法获取当前身份",
      response.status,
      problem?.code ?? null,
    );
  }
  return (await response.json()) as AuthSnapshot;
}

async function loadMe(): Promise<AuthSnapshot> {
  const storedBusinessUnit = readStoredBusinessUnit();
  try {
    const snapshot = await requestMe(storedBusinessUnit ?? undefined);
    setActiveBusinessUnitInMemory(snapshot.active_business_unit_id);
    return snapshot;
  } catch (error) {
    if (
      error instanceof AuthRequestError &&
      error.status === 403 &&
      error.code === "BUSINESS_UNIT_ACCESS_DENIED" &&
      storedBusinessUnit
    ) {
      clearStoredBusinessUnit();
      const snapshot = await requestMe();
      setActiveBusinessUnitInMemory(snapshot.active_business_unit_id);
      writeStoredBusinessUnit(snapshot.active_business_unit_id);
      return snapshot;
    }
    throw error;
  }
}

export interface AuthContextValue {
  me: AuthSnapshot;
  role: string;
  roleLabel: string;
  activeBusinessUnitId: string;
  activeBusinessUnitLabel: string;
  capabilities: ReadonlySet<string>;
  isTestMode: boolean;
  testIdentity: TestIdentityProfile | null;
  hasCapability: (capability: Capability) => boolean;
  canAccessPath: (path: string) => boolean;
  refreshAuth: () => Promise<void>;
  switchBusinessUnit: (businessUnitId: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthGate");
  }
  return value;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<AuthRequestError | Error | null>(null);
  const [me, setMe] = useState<AuthSnapshot | null>(null);

  const bootstrap = useCallback(async () => {
    await initializeAuth();
    const snapshot = await loadMe();
    setMe(snapshot);
    setState("ready");
  }, []);

  useEffect(() => {
    let active = true;
    bootstrap()
      .then(() => undefined)
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason : new Error("身份验证失败"));
        setState("error");
      });
    return () => {
      active = false;
    };
  }, [bootstrap]);

  const refreshAuth = useCallback(async () => {
    const snapshot = await loadMe();
    setMe(snapshot);
  }, []);

  const switchBusinessUnit = useCallback(
    async (businessUnitId: string) => {
      writeStoredBusinessUnit(businessUnitId);
      const snapshot = await loadMe();
      setMe(snapshot);
      await queryClient.invalidateQueries();
    },
    [queryClient],
  );

  const value = useMemo<AuthContextValue | null>(() => {
    if (!me) return null;
    const capabilities = new Set<string>(me.capabilities);
    return {
      me,
      role: me.role,
      roleLabel: me.role_label,
      activeBusinessUnitId: me.active_business_unit_id,
      activeBusinessUnitLabel:
        me.business_unit_labels[me.active_business_unit_id] ??
        me.active_business_unit_id,
      capabilities,
      isTestMode: isTestIdentityMode(),
      testIdentity: getStoredTestProfile(),
      hasCapability: (capability) => capabilities.has(capability),
      canAccessPath: (path) => canAccessCapabilityPath(capabilities, path),
      refreshAuth,
      switchBusinessUnit,
    };
  }, [me, refreshAuth, switchBusinessUnit]);

  if (state === "error") {
    const denied =
      error instanceof AuthRequestError &&
      (error.status === 403 || error.status === 401);
    return (
      <div className="auth-screen">
        <Result
          status={denied ? "403" : "error"}
          title={denied ? "当前身份无权进入该工作区" : "无法完成身份验证"}
          subTitle={
            error instanceof AuthRequestError
              ? `${error.message}（${error.code ?? error.status}）`
              : error?.message ?? "请稍后重试"
          }
          extra={
            authMode === "oidc" ? (
              <Button
                type="primary"
                onClick={() => login().catch(() => undefined)}
              >
                重新登录
              </Button>
            ) : (
              <Button
                type="primary"
                onClick={() => {
                  setState("loading");
                  setError(null);
                  bootstrap().catch((reason: unknown) => {
                    setError(
                      reason instanceof Error
                        ? reason
                        : new Error("身份验证失败"),
                    );
                    setState("error");
                  });
                }}
              >
                重试
              </Button>
            )
          }
        />
      </div>
    );
  }

  if (state !== "ready" || !value) {
    return (
      <div className="auth-screen">
        <Spin size="large" />
        <span>
          {authMode === "oidc" ? "正在验证企业身份…" : "正在启动工作台…"}
        </span>
      </div>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
