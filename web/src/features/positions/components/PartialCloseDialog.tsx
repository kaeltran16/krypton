import { useState } from "react";
import { api, type Position } from "../../../shared/lib/api";
import { formatPair } from "../../../shared/lib/format";
import { Button } from "../../../shared/components/Button";
import { ActionSheet } from "./ActionSheet";

interface Props {
  position: Position;
  onClose: () => void;
  onSuccess: () => void;
}

const PRESETS = [25, 50, 75];

export function PartialCloseDialog({ position, onClose, onSuccess }: Props) {
  const [size, setSize] = useState("");
  const [selectedPct, setSelectedPct] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  function applyPercent(pct: number) {
    const val = (position.size * pct / 100);
    setSize(String(val));
    setSelectedPct(pct);
  }

  async function handleSubmit() {
    if (!size || parseFloat(size) <= 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.partialClose({
        pair: position.pair,
        pos_side: position.side,
        size,
      });
      if (result.success) {
        setSuccess(true);
        setTimeout(onSuccess, 800);
      } else {
        setError(result.error || "Partial close failed — check size and try again");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error — check connection and retry");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ActionSheet title={`Partial Close ${formatPair(position.pair)}`} onClose={onClose}>
      <div className="text-sm text-on-surface-variant">
        Current size: <span className="font-mono font-medium text-on-surface">{position.size}</span>
      </div>

      <div className="flex gap-2">
        {PRESETS.map((pct) => (
          <Button key={pct} variant={selectedPct === pct ? "primary" : "secondary"} size="sm" onClick={() => applyPercent(pct)}>
            {pct}%
          </Button>
        ))}
      </div>

      <div>
        <label className="text-sm text-on-surface-variant block mb-1">Size to close</label>
        <input
          type="text"
          inputMode="decimal"
          value={size}
          onChange={(e) => { setSize(e.target.value); setSelectedPct(null); }}
          placeholder="0"
          className="w-full p-3 bg-surface-container-lowest rounded-lg border border-outline-variant/10 font-mono focus:border-primary/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        />
      </div>

      {error && (
        <div className="p-3 rounded-lg text-sm bg-short/10 text-short">{error}</div>
      )}
      {success && (
        <div className="p-3 rounded-lg text-sm bg-long/10 text-long">Partial close executed</div>
      )}

      {!success && (
        <Button variant="short" size="lg" loading={submitting} onClick={handleSubmit} disabled={!size}>
          Close {size || "0"} contracts
        </Button>
      )}
    </ActionSheet>
  );
}
