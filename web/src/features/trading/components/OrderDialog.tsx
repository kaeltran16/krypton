import { useState, useRef, useEffect } from "react";
import type { Signal } from "../../signals/types";
import { api, type RiskCheckResult } from "../../../shared/lib/api";
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
  const [riskCheck, setRiskCheck] = useState<RiskCheckResult | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [overrideText, setOverrideText] = useState("");
  const [showOverride, setShowOverride] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (signal) {
      setResult(null);
      setRiskCheck(null);
      setRiskLoading(true);
      setOverrideText("");
      setShowOverride(false);

      // Pre-fill size from risk metrics if available
      if (signal.risk_metrics) {
        setSize(String(signal.risk_metrics.position_size_base));
      } else {
        setSize("1");
      }

      dialog.showModal();

      // Run risk check
      const sizeUsd = signal.risk_metrics?.position_size_usd ?? signal.levels.entry * 1;
      api.checkRisk({
        pair: signal.pair,
        direction: signal.direction,
        size_usd: sizeUsd,
      }).then(setRiskCheck).catch(() => {
        // Risk check unavailable — allow trading
        setRiskCheck(null);
      }).finally(() => setRiskLoading(false));
    } else {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const side = signal.direction === "LONG" ? "buy" : "sell";
  const isBlocked = riskCheck?.status === "BLOCKED";
  const isWarning = riskCheck?.status === "WARNING";
  const overrideConfirmed = overrideText === "OVERRIDE";

  async function handleSubmit() {
    if (!signal) return;
    setSubmitting(true);
    try {
      const orderReq: Parameters<typeof api.placeOrder>[0] = {
        pair: signal.pair,
        side,
        size,
        sl_price: String(signal.levels.stop_loss),
        tp_price: String(signal.levels.take_profit_1),
      };
      if (isBlocked && overrideConfirmed) {
        orderReq.override = true;
        orderReq.override_rules = riskCheck!.rules
          .filter(r => r.status === "BLOCKED")
          .map(r => r.rule);
      }
      const res = await api.placeOrder(orderReq);
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
        {/* Risk check banner */}
        {riskLoading && (
          <div className="p-3 rounded-lg bg-card-hover text-muted text-sm animate-pulse">
            Checking risk rules...
          </div>
        )}
        {!riskLoading && riskCheck && isBlocked && (
          <div className="p-3 rounded-lg bg-short/10 border border-short/30">
            <div className="text-sm font-medium text-short mb-1">Trade Blocked</div>
            {riskCheck.rules.filter(r => r.status === "BLOCKED").map(r => (
              <div key={r.rule} className="text-xs text-short/80">{r.reason}</div>
            ))}
            {!showOverride ? (
              <button
                onClick={() => setShowOverride(true)}
                className="mt-2 text-xs text-muted underline"
              >
                Override
              </button>
            ) : (
              <div className="mt-2">
                <div className="text-xs text-muted mb-1">Type OVERRIDE to confirm</div>
                <input
                  type="text"
                  value={overrideText}
                  onChange={(e) => setOverrideText(e.target.value)}
                  placeholder="OVERRIDE"
                  className="w-full p-2 bg-surface rounded border border-gray-800 text-sm font-mono focus:border-short/50 focus:outline-none"
                />
              </div>
            )}
          </div>
        )}
        {!riskLoading && riskCheck && isWarning && (
          <div className="p-3 rounded-lg bg-accent/10 border border-accent/30">
            <div className="text-sm font-medium text-accent mb-1">Risk Advisory</div>
            {riskCheck.rules.filter(r => r.status === "WARNING").map(r => (
              <div key={r.rule} className="text-xs text-accent/80">{r.reason}</div>
            ))}
          </div>
        )}
        {!riskLoading && !riskCheck && !result && (
          <div className="p-2 rounded-lg bg-accent/10 text-accent text-xs">
            Risk check unavailable — proceed with caution
          </div>
        )}

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
          {signal.risk_metrics && (
            <>
              <div className="text-gray-400">Risk</div>
              <div className="font-mono text-short">${signal.risk_metrics.risk_amount_usd.toFixed(0)} ({signal.risk_metrics.risk_pct}%)</div>
              <div className="text-gray-400">R:R</div>
              <div className="font-mono text-long">
                {signal.risk_metrics.tp1_rr != null ? `1:${signal.risk_metrics.tp1_rr}` : "—"}
                {signal.risk_metrics.tp2_rr != null ? ` / 1:${signal.risk_metrics.tp2_rr}` : ""}
              </div>
            </>
          )}
        </div>

        <div>
          <label className="text-sm text-gray-400 block mb-1">
            Size {signal.risk_metrics ? `(recommended: ${signal.risk_metrics.position_size_base})` : "(contracts)"}
          </label>
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
        {result?.warning && (
          <div className="p-3 rounded-lg text-sm bg-accent/10 text-accent">
            {result.warning}
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
            disabled={submitting || (isBlocked && !overrideConfirmed)}
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
