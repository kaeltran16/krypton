import { useState, useRef, useEffect } from "react";
import type { Signal } from "../../signals/types";
import { api } from "../../../shared/lib/api";
import { formatPrice } from "../../../shared/lib/format";

interface Props {
  signal: Signal | null;
  onClose: () => void;
}

export function OrderDialog({ signal, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [size, setSize] = useState("1");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; error?: string } | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (signal) {
      setResult(null);
      setSize("1");
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const side = signal.direction === "LONG" ? "buy" : "sell";

  async function handleSubmit() {
    if (!signal) return;
    setSubmitting(true);
    try {
      const res = await api.placeOrder({
        pair: signal.pair,
        side,
        size,
        sl_price: String(signal.levels.stop_loss),
        tp_price: String(signal.levels.take_profit_1),
      });
      setResult(res);
    } catch (e) {
      setResult({ success: false, error: e instanceof Error ? e.message : "Order failed" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }} className="bg-card text-white rounded-xl w-full max-w-md border border-gray-800 backdrop:bg-black/60">
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <span className="text-lg font-bold">Confirm Order</span>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">&times;</button>
        </div>
      </div>

      <div className="p-4 space-y-3">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="text-gray-400">Pair</div>
          <div className="font-mono">{signal.pair}</div>
          <div className="text-gray-400">Side</div>
          <div className={`font-mono ${side === "buy" ? "text-long" : "text-short"}`}>{side.toUpperCase()}</div>
          <div className="text-gray-400">Entry</div>
          <div className="font-mono">{formatPrice(signal.levels.entry)}</div>
          <div className="text-gray-400">Stop Loss</div>
          <div className="font-mono text-short">{formatPrice(signal.levels.stop_loss)}</div>
          <div className="text-gray-400">Take Profit</div>
          <div className="font-mono text-long">{formatPrice(signal.levels.take_profit_1)}</div>
        </div>

        <div>
          <label className="text-sm text-gray-400 block mb-1">Size (contracts)</label>
          <input
            type="text"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            className="w-full p-3 bg-surface rounded-lg border border-gray-800 font-mono focus:border-long/50 focus:outline-none"
          />
        </div>

        {result && (
          <div className={`p-3 rounded-lg text-sm ${result.success ? "bg-long/10 text-long" : "bg-short/10 text-short"}`}>
            {result.success ? "Order placed successfully" : result.error}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-gray-800">
        {result?.success ? (
          <button onClick={onClose} className="w-full py-3 rounded-lg bg-card text-white font-medium">
            Close
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className={`w-full py-3 rounded-lg font-medium ${
              side === "buy" ? "bg-long text-black" : "bg-short text-white"
            } disabled:opacity-50`}
          >
            {submitting ? "Placing order..." : `${side.toUpperCase()} ${signal.pair}`}
          </button>
        )}
      </div>
    </dialog>
  );
}
