import { useState, useEffect } from "react";
import { api, type Position, type AlgoOrder } from "../../../shared/lib/api";
import { formatPair, formatPricePrecision } from "../../../shared/lib/format";
import { Button } from "../../../shared/components/Button";
import { Skeleton } from "../../../shared/components/Skeleton";
import { ActionSheet } from "./ActionSheet";

interface Props {
  position: Position;
  onClose: () => void;
  onSuccess: () => void;
}

export function AdjustSlTpDialog({ position, onClose, onSuccess }: Props) {
  const [slPrice, setSlPrice] = useState("");
  const [tpPrice, setTpPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);
  const [loadingAlgos, setLoadingAlgos] = useState(true);
  const [currentAlgos, setCurrentAlgos] = useState<AlgoOrder[]>([]);

  useEffect(() => {
    api.getAlgoOrders(position.pair)
      .then((algos) => {
        setCurrentAlgos(algos);
        if (algos.length > 0) {
          const a = algos[0];
          if (a.sl_trigger_price) setSlPrice(String(a.sl_trigger_price));
          if (a.tp_trigger_price) setTpPrice(String(a.tp_trigger_price));
        }
      })
      .catch(() => {})
      .finally(() => setLoadingAlgos(false));
  }, [position.pair]);

  async function handleSubmit() {
    if (!slPrice && !tpPrice) return;
    setSubmitting(true);
    setError(null);
    setWarning(null);
    try {
      const side = position.side === "long" ? "buy" : "sell";
      const result = await api.amendAlgo({
        pair: position.pair,
        side,
        size: String(position.size),
        sl_price: slPrice || undefined,
        tp_price: tpPrice || undefined,
      });
      if (result.success) {
        setSuccess(true);
        setTimeout(onSuccess, 800);
      } else if (result.sl_tp_removed) {
        setWarning("Previous SL/TP was removed but new placement failed. Tap Retry to re-submit.");
        setError(result.error || "Placement failed");
      } else {
        setError(result.error || "Failed to adjust SL/TP — verify prices and retry");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error — check connection and retry");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRetry() {
    // Re-fetch algo state first to avoid duplicates
    setSubmitting(true);
    setError(null);
    setWarning(null);
    try {
      const algos = await api.getAlgoOrders(position.pair);
      if (algos.length > 0) {
        setError("An algo order already exists — please cancel it first or refresh.");
        setSubmitting(false);
        return;
      }
      await handleSubmit();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed — check connection");
      setSubmitting(false);
    }
  }

  return (
    <ActionSheet title={`SL/TP — ${formatPair(position.pair)}`} onClose={onClose}>
      {loadingAlgos ? (
        <Skeleton height="h-20" />
      ) : (
        <>
          {currentAlgos.length > 0 && (
            <div className="text-xs text-on-surface-variant">
              Current: SL {currentAlgos[0].sl_trigger_price ?? "—"} / TP {currentAlgos[0].tp_trigger_price ?? "—"}
            </div>
          )}

          <div className="text-xs text-on-surface-variant">
            Mark: <span className="font-mono">${formatPricePrecision(position.mark_price, position.pair)}</span>
          </div>

          <div>
            <label className="text-sm text-on-surface-variant block mb-1">Stop Loss</label>
            <input
              type="text"
              inputMode="decimal"
              value={slPrice}
              onChange={(e) => setSlPrice(e.target.value)}
              placeholder="SL price"
              className="w-full p-3 bg-surface-container-lowest rounded-lg border border-outline-variant/10 font-mono focus:border-short/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            />
          </div>

          <div>
            <label className="text-sm text-on-surface-variant block mb-1">Take Profit</label>
            <input
              type="text"
              inputMode="decimal"
              value={tpPrice}
              onChange={(e) => setTpPrice(e.target.value)}
              placeholder="TP price"
              className="w-full p-3 bg-surface-container-lowest rounded-lg border border-outline-variant/10 font-mono focus:border-long/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            />
          </div>

          {error && (
            <div className="p-3 rounded-lg text-sm bg-short/10 text-short">{error}</div>
          )}
          {warning && (
            <div className="p-3 rounded-lg text-sm bg-primary/10 text-primary">{warning}</div>
          )}
          {success && (
            <div className="p-3 rounded-lg text-sm bg-long/10 text-long">SL/TP updated</div>
          )}

          {!success && !warning && (
            <Button variant="primary" size="lg" loading={submitting} onClick={handleSubmit} disabled={!slPrice && !tpPrice}>
              Update SL/TP
            </Button>
          )}
          {warning && !success && (
            <Button variant="primary" size="lg" loading={submitting} onClick={handleRetry}>
              Retry Placement
            </Button>
          )}
        </>
      )}
    </ActionSheet>
  );
}
