"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import type { AnalyticsData, BaselineData } from "./lib/types";

const REFRESH_MS = 10000;
const DAY_MS = 24 * 3_600_000;

export type AnalyticsState = { data: AnalyticsData | null; baseline: BaselineData | null; failed: boolean };

const Context = createContext<AnalyticsState>({ data: null, baseline: null, failed: false });

export function useAnalytics(): AnalyticsState {
  return useContext(Context);
}

// One read of the last 24 hours of /api/analytics (and the REL-30 baseline once) shared by the headline band and the
// AI section, so every figure on the page comes from the same response. The API key stays on the server.
export default function AnalyticsProvider({
  children,
  intervalMs = REFRESH_MS,
}: {
  children: ReactNode;
  intervalMs?: number;
}) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [baseline, setBaseline] = useState<BaselineData | null>(null);
  const [failed, setFailed] = useState(false);
  const latest = useRef(0);

  const load = useCallback(async () => {
    const ticket = ++latest.current;
    const to = new Date();
    const query = new URLSearchParams({
      from: new Date(to.getTime() - DAY_MS).toISOString(),
      to: to.toISOString(),
    });
    try {
      const res = await fetch(`/api/analytics?${query.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const body = (await res.json()) as AnalyticsData;
      if (ticket !== latest.current) return;
      setData(body);
      setFailed(false);
    } catch {
      if (ticket === latest.current) setFailed(true);
    }
  }, []);

  useEffect(() => {
    // Deferred a tick so the effect itself sets no state synchronously.
    const first = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load, intervalMs]);

  useEffect(() => {
    let active = true;
    const read = async () => {
      try {
        const res = await fetch("/api/analytics/baseline", { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as BaselineData;
        if (active) setBaseline(body);
      } catch {
        if (active) setBaseline({ available: false });
      }
    };
    const first = setTimeout(() => void read(), 0);
    return () => {
      active = false;
      clearTimeout(first);
    };
  }, []);

  return <Context.Provider value={{ data, baseline, failed }}>{children}</Context.Provider>;
}
