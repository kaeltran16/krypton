import { useState, useEffect } from "react";
import { api } from "../../../shared/lib/api";
import { useEngineStore } from "../../engine/store";
import type { ParameterDiff } from "../../engine/types";

interface Props {
  changes: Record<string, number>;
  onClose: () => void;
}

export default function ApplyModal({ changes, onClose }: Props) {
  const [diff, setDiff] = useState<ParameterDiff[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = useEngineStore((s) => s.refresh);

  const preview = async () => {
    setLoading(true);
    try {
      const result = await api.previewEngineApply(changes);
      setDiff(result.diff);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const confirm = async () => {
    setLoading(true);
    try {
      await api.confirmEngineApply(changes);
      setApplied(true);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { preview(); }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-surface-container rounded-xl p-4 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto">
        <h3 className="text-sm font-medium mb-3">
          {applied ? "Changes Applied" : "Review Parameter Changes"}
        </h3>

        {error && <p className="text-xs text-error mb-2">{error}</p>}

        {diff && (
          <table className="w-full text-xs mb-3">
            <thead>
              <tr className="text-on-surface-variant border-b border-outline-variant">
                <th className="text-left py-1">Parameter</th>
                <th className="text-right py-1">Current</th>
                <th className="text-right py-1">Proposed</th>
              </tr>
            </thead>
            <tbody>
              {diff.map((d) => (
                <tr key={d.path} className="border-b border-outline-variant/10">
                  <td className="py-1.5 text-on-surface-variant font-mono">{d.path.split(".").pop()}</td>
                  <td className="text-right py-1.5 font-mono">{d.current ?? "\u2014"}</td>
                  <td className="text-right py-1.5 font-mono text-primary">{d.proposed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 text-xs text-on-surface-variant hover:text-on-surface">
            {applied ? "Close" : "Cancel"}
          </button>
          {!applied && diff && (
            <button
              onClick={confirm}
              disabled={loading}
              className="px-3 py-1.5 text-xs bg-primary/15 text-primary rounded-lg hover:bg-primary/30 disabled:opacity-50"
            >
              {loading ? "Applying..." : "Confirm Apply"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
