import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchReport } from "../api";
import type { ReportPayload } from "../types";

interface ReportContextValue {
  short: number;
  long: number;
  setShort: (value: number) => void;
  setLong: (value: number) => void;
  report: ReportPayload | null;
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
}

const ReportContext = createContext<ReportContextValue | null>(null);

export function ReportProvider({ children }: { children: ReactNode }) {
  const [short, setShort] = useState(3);
  const [long, setLong] = useState(7);
  const [report, setReport] = useState<ReportPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setReport(await fetchReport(short, long));
    } catch (err) {
      setReport(null);
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [long, short]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo(
    () => ({ short, long, setShort, setLong, report, loading, error, refresh }),
    [short, long, report, loading, error, refresh],
  );

  return <ReportContext.Provider value={value}>{children}</ReportContext.Provider>;
}

export function useReport() {
  const context = useContext(ReportContext);
  if (!context) {
    throw new Error("useReport must be used within ReportProvider");
  }
  return context;
}
