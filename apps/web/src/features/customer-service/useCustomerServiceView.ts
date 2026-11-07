import { useEffect, useState } from "react";

import {
  viewModeStorageKey,
  type CustomerDemoScenario,
  type CustomerServiceSection,
  type CustomerServiceSurfaceMode,
} from "./model";

export interface UseCustomerServiceViewOptions {
  technicalMode: boolean;
  section: CustomerServiceSection;
}

export function useCustomerServiceView({
  technicalMode,
  section,
}: UseCustomerServiceViewOptions) {
  const [demoScenario, setDemoScenario] = useState<CustomerDemoScenario>(() =>
    new URLSearchParams(window.location.search).get("scenario") === "ecommerce"
      ? "ecommerce"
      : "enterprise",
  );
  const [viewMode, setViewMode] = useState<CustomerServiceSurfaceMode>(() => {
    const requestedPane = new URLSearchParams(
      window.location.search,
    ).get("pane");
    if (requestedPane === "workbench") return "workspace";
    if (requestedPane === "admin" && technicalMode) return "admin";
    if (section === "workbench") return "workspace";
    if (
      section === "admin" ||
      section === "approvals" ||
      section === "incidents"
    ) {
      return "admin";
    }
    if (section === "chat") return "chat";
    const storedMode = window.localStorage.getItem(viewModeStorageKey);
    return storedMode === "admin" && technicalMode ? "admin" : "chat";
  });

  useEffect(() => {
    const onPopState = () => {
      setDemoScenario(
        new URLSearchParams(window.location.search).get("scenario") ===
          "ecommerce"
          ? "ecommerce"
          : "enterprise",
      );
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("pane")) return;
    url.searchParams.delete("pane");
    window.history.replaceState({}, document.title, url);
  }, []);

  useEffect(() => {
    if (!technicalMode && viewMode === "admin") {
      setViewMode("chat");
    }
  }, [technicalMode, viewMode]);

  useEffect(() => {
    window.localStorage.setItem(viewModeStorageKey, viewMode);
  }, [viewMode]);

  return { demoScenario, viewMode, setViewMode };
}
