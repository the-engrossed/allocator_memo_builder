import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { EvidenceRecord } from "../types/api";
import { AuditDrawer, type DrawerState } from "./AuditDrawer";

interface EvidenceDrawerApi {
  open: (evidenceId: string, trigger: HTMLElement | null) => void;
}

const EvidenceDrawerContext = createContext<EvidenceDrawerApi | null>(null);

/** Null outside a provider, so chips stay inert where no drawer exists. */
export function useEvidenceDrawer(): EvidenceDrawerApi | null {
  return useContext(EvidenceDrawerContext);
}

type Registry = { status: "idle" } | { status: "loading" } | { status: "error"; message: string } | {
  status: "ready";
  records: Map<string, EvidenceRecord>;
};

interface ProviderProps {
  /** Resolves the evidence records the drawer may show (a memo snapshot or a run registry). */
  load: () => Promise<EvidenceRecord[]>;
  /** Changing this discards cached records (a new run or memo revision). */
  cacheKey: string;
  children: ReactNode;
}

export function EvidenceDrawerProvider({ load, cacheKey, children }: ProviderProps) {
  const [registry, setRegistry] = useState<Registry>({ status: "idle" });
  const [openId, setOpenId] = useState<string | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  const registryRef = useRef(registry);
  registryRef.current = registry;

  useEffect(() => {
    setRegistry({ status: "idle" });
    setOpenId(null);
  }, [cacheKey]);

  const fetchRecords = useCallback(() => {
    setRegistry({ status: "loading" });
    loadRef
      .current()
      .then((records) =>
        setRegistry({ status: "ready", records: new Map(records.map((r) => [r.evidence_id, r])) }),
      )
      .catch((cause: unknown) =>
        setRegistry({
          status: "error",
          message: cause instanceof Error && cause.message ? cause.message : "Could not load evidence.",
        }),
      );
  }, []);

  const open = useCallback(
    (evidenceId: string, element: HTMLElement | null) => {
      trigger.current = element;
      setOpenId(evidenceId);
      const status = registryRef.current.status;
      if (status === "idle" || status === "error") {
        fetchRecords();
      }
    },
    [fetchRecords],
  );

  const close = useCallback(() => {
    setOpenId(null);
    const element = trigger.current;
    trigger.current = null;
    element?.focus();
  }, []);

  let state: DrawerState = { status: "loading" };
  if (registry.status === "error") {
    state = { status: "error", message: registry.message };
  } else if (registry.status === "ready" && openId) {
    state = { status: "ready", record: registry.records.get(openId) ?? null };
  }

  return (
    <EvidenceDrawerContext.Provider value={{ open }}>
      {children}
      {openId && <AuditDrawer evidenceId={openId} state={state} onClose={close} onRetry={fetchRecords} />}
    </EvidenceDrawerContext.Provider>
  );
}
