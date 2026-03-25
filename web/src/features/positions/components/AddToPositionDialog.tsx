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

export function AddToPositionDialog({ position, onClose, onSuccess }: Props) {
  const [size, setSize] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit() {
    if (!size || parseFloat(size) <= 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const side = position.side === "long" ? "buy" : "sell";
      const result = await api.placeOrder({
        pair: position.pair,
        side,
        size,
      });
      if (result.success) {
        setSuccess(true);
        setTimeout(onSuccess, 800);
      } else {
        setError(result.error || "Order failed");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ActionSheet title={`Add to ${formatPair(position.pair)} ${position.side.toUpperCase()}`} onClose={onClose}>
      <div className="text-sm text-on-surface-variant">
        Current size: <span className="font-mono font-medium text-on-surface">{position.size}</span>
      </div>

      <div>
        <label className="text-sm text-on-surface-variant block mb-1">Additional size</label>
        <input
          type="text"
          inputMode="decimal"
          value={size}
          onChange={(e) => setSize(e.target.value)}
          placeholder="0"
          className="w-full p-3 bg-surface-container-lowest rounded-lg border border-outline-variant/10 font-mono focus:border-primary/50 focus:outline-none"
        />
      </div>

      {error && (
        <div className="p-3 rounded-lg text-sm bg-short/10 text-short">{error}</div>
      )}
      {success && (
        <div className="p-3 rounded-lg text-sm bg-long/10 text-long">Position added</div>
      )}

      {!success && (
        <Button
          variant={position.side === "long" ? "long" : "short"}
          size="lg"
          loading={submitting}
          onClick={handleSubmit}
          disabled={!size}
        >
          Add {size || "0"} contracts
        </Button>
      )}
    </ActionSheet>
  );
}
