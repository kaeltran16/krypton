import { useState, useEffect, useCallback } from "react";
import { Check, AlertTriangle, Lock, RefreshCw } from "lucide-react";
import { api, type RiskSettings, type RiskRule, type RiskState, type RiskStatus } from "../../../shared/lib/api";
import { Button } from "../../../shared/components/Button";
import { ProgressBar } from "../../../shared/components/ProgressBar";
import { Skeleton } from "../../../shared/components/Skeleton";

type Status = "OK" | "WARNING" | "BLOCKED";

const STATUS_STYLES: Record<Status, { dot: string; text: string; icon: typeof Check }> = {
  OK: { dot: "text-long", text: "text-long", icon: Check },
  WARNING: { dot: "text-orange", text: "text-orange", icon: AlertTriangle },
  BLOCKED: { dot: "text-error", text: "text-error", icon: Lock },
};

function getRule(rules: RiskRule[], key: string): RiskRule | undefined {
  return rules.find((r) => r.rule === key);
}

function statusFor(rules: RiskRule[], key: string): Status {
  return (getRule(rules, key)?.status ?? "OK") as Status;
}

function StatusIcon({ status }: { status: Status }) {
  const style = STATUS_STYLES[status];
  const Icon = style.icon;
  return <Icon className={`w-3.5 h-3.5 ${style.dot}`} />;
}

export default function RiskPage() {
  const [data, setData] = useState<RiskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const result = await api.getRiskStatus();
      setData(result);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  async function update(field: string, value: number | null) {
    if (!data) return;
    const prev = data;
    setSaving(true);
    setSectionError(null);
    try {
      await api.updateRiskSettings({ [field]: value });
      const refreshed = await api.getRiskStatus();
      setData(refreshed);
    } catch {
      setData(prev);
      setSectionError(field);
    } finally {
      setSaving(false);
    }
  }

  if (loading && !data) {
    return (
      <div className="p-3 space-y-3">
        <Skeleton count={3} height="h-28" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-3 flex flex-col items-center gap-3 pt-16">
        <p className="text-sm text-on-surface-variant">Failed to load risk status</p>
        <Button variant="primary" size="sm" onClick={fetchStatus}>Retry</Button>
      </div>
    );
  }

  if (!data) return null;

  const { settings, state, rules, overall_status } = data;
  const overallStyle = STATUS_STYLES[overall_status as Status];
  const OverallIcon = overallStyle.icon;
  const overallLabel = overall_status === "OK" ? "All Clear" : overall_status === "WARNING" ? "Warning" : "Blocked";

  return (
    <div className="p-3 space-y-3">
      {/* Overall status + refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2" role="status" aria-live="polite">
          <OverallIcon className={`w-4 h-4 ${overallStyle.dot}`} />
          <span className={`text-sm font-bold ${overallStyle.text}`}>{overallLabel}</span>
        </div>
        <Button
          variant="ghost"
          icon={<RefreshCw className={`w-4 h-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`} />}
          onClick={fetchStatus}
          disabled={loading}
          aria-label="Refresh risk status"
        />
      </div>

      {/* 1. Risk Per Trade */}
      <RiskSection title="Risk Per Trade" status="OK">
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface mb-3">
          {(settings.risk_per_trade * 100).toFixed(1)}%
        </div>
        <PresetButtons
          options={[
            { label: "0.5%", value: 0.005 },
            { label: "1%", value: 0.01 },
            { label: "2%", value: 0.02 },
          ]}
          current={settings.risk_per_trade}
          onSelect={(v) => update("risk_per_trade", v)}
          saving={saving}
        />
        {sectionError === "risk_per_trade" && <SectionError />}
      </RiskSection>

      {/* 2. Daily Loss Limit */}
      <DailyLossSection settings={settings} state={state} rules={rules} update={update} saving={saving} sectionError={sectionError} />

      {/* 3. Max Positions */}
      <RiskSection title="Max Positions" status={statusFor(rules, "max_concurrent")}>
        <div className="flex items-center justify-between mb-3">
          <span className={`font-headline text-2xl font-bold tabular-nums ${STATUS_STYLES[statusFor(rules, "max_concurrent")].text}`}>
            {state.open_positions_count} / {settings.max_concurrent_positions}
          </span>
        </div>
        <PresetButtons
          options={[
            { label: "2", value: 2 },
            { label: "3", value: 3 },
            { label: "5", value: 5 },
          ]}
          current={settings.max_concurrent_positions}
          onSelect={(v) => update("max_concurrent_positions", v)}
          saving={saving}
        />
        <RuleReason rules={rules} ruleKey="max_concurrent" />
        {sectionError === "max_concurrent_positions" && <SectionError />}
      </RiskSection>

      {/* 4. Max Exposure */}
      <MaxExposureSection settings={settings} state={state} rules={rules} update={update} saving={saving} sectionError={sectionError} />

      {/* 5. Max Position Size */}
      <RiskSection title="Max Position Size" status="OK">
        <MaxPositionSizeInput
          value={settings.max_position_size_usd}
          onSave={(v) => update("max_position_size_usd", v)}
          saving={saving}
        />
        {sectionError === "max_position_size_usd" && <SectionError />}
      </RiskSection>

      {/* 6. Max Risk Per Trade */}
      <RiskSection title="Max Risk Per Trade" status="OK">
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface mb-3">
          {(settings.max_risk_per_trade_pct * 100).toFixed(0)}%
        </div>
        <PresetButtons
          options={[
            { label: "1%", value: 0.01 },
            { label: "2%", value: 0.02 },
            { label: "5%", value: 0.05 },
          ]}
          current={settings.max_risk_per_trade_pct}
          onSelect={(v) => update("max_risk_per_trade_pct", v)}
          saving={saving}
        />
        {sectionError === "max_risk_per_trade_pct" && <SectionError />}
      </RiskSection>

      {/* 7. Loss Cooldown */}
      <CooldownSection settings={settings} state={state} rules={rules} update={update} saving={saving} sectionError={sectionError} />
    </div>
  );
}

/* ── Shared sub-components ── */

function RiskSection({ title, status, children }: { title: string; status: Status; children: React.ReactNode }) {
  return (
    <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <StatusIcon status={status} />
        <span className="text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">{title}</span>
      </div>
      {children}
    </section>
  );
}

function PresetButtons({ options, current, onSelect, saving, compare }: {
  options: { label: string; value: number }[];
  current: number;
  onSelect: (v: number) => void;
  saving: boolean;
  compare?: (a: number, b: number) => boolean;
}) {
  const isActive = compare ?? ((a: number, b: number) => Math.abs(a - b) < 0.0001);
  return (
    <div className="flex gap-2">
      {options.map((opt) => (
        <button
          key={opt.label}
          onClick={() => onSelect(opt.value)}
          disabled={saving}
          className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
            isActive(current, opt.value)
              ? "bg-primary/15 text-primary border border-primary/30"
              : "bg-surface-container-lowest text-on-surface-variant"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function RuleReason({ rules, ruleKey }: { rules: RiskRule[]; ruleKey: string }) {
  const rule = getRule(rules, ruleKey);
  if (!rule) return null;
  const style = STATUS_STYLES[rule.status as Status];
  return <p className={`text-[11px] mt-2 ${style.text}`}>{rule.reason}</p>;
}

function SectionError() {
  return <p className="text-[11px] mt-2 text-error">Update failed. Try again.</p>;
}

function MaxPositionSizeInput({ value, onSave, saving }: {
  value: number | null;
  onSave: (v: number | null) => void;
  saving: boolean;
}) {
  const [input, setInput] = useState(value != null ? String(value) : "");
  const [inputError, setInputError] = useState<string | null>(null);

  useEffect(() => {
    const next = value != null ? String(value) : "";
    if (next !== input) setInput(next);
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps -- intentionally excludes input to avoid overwriting user typing

  function handleSave() {
    const trimmed = input.trim();
    if (trimmed === "") {
      setInputError(null);
      onSave(null);
      return;
    }
    const num = parseFloat(trimmed);
    if (isNaN(num) || num <= 0) {
      setInputError("Must be a positive number");
      return;
    }
    setInputError(null);
    onSave(num);
  }

  return (
    <div>
      <label htmlFor="max-position-size" className="block text-xs font-bold text-on-surface-variant mb-1.5">
        Max Position Size
      </label>
      <div className="flex items-center gap-2">
        <input
          id="max-position-size"
          type="text"
          inputMode="decimal"
          value={input}
          onChange={(e) => { setInput(e.target.value); setInputError(null); }}
          onBlur={handleSave}
          onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
          disabled={saving}
          placeholder="Unlimited"
          className="flex-1 min-h-[44px] px-3 py-2 text-sm bg-surface-container-lowest border border-outline-variant/20 rounded-lg text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <span className="text-xs font-bold text-on-surface-variant">USD</span>
      </div>
      {inputError && <p className="text-[11px] mt-1 text-error">{inputError}</p>}
    </div>
  );
}

/* ── Sections with progress bars ── */

function DailyLossSection({ settings, state, rules, update, saving, sectionError }: {
  settings: RiskSettings; state: RiskState; rules: RiskRule[];
  update: (field: string, value: number | null) => void; saving: boolean; sectionError: string | null;
}) {
  const status = statusFor(rules, "daily_loss_limit");
  const style = STATUS_STYLES[status];
  const usagePct = settings.daily_loss_limit_pct > 0
    ? Math.min(Math.abs(state.daily_pnl_pct) / settings.daily_loss_limit_pct * 100, 100)
    : 0;
  const rule = getRule(rules, "daily_loss_limit");

  return (
    <RiskSection title="Daily Loss Limit" status={status}>
      <div className={`font-headline text-2xl font-bold tabular-nums mb-1 ${style.text}`}>
        {(state.daily_pnl_pct * 100).toFixed(1)}% / {(settings.daily_loss_limit_pct * 100).toFixed(0)}%
      </div>
      <ProgressBar
        value={usagePct}
        color={status === "BLOCKED" ? "bg-error" : status === "WARNING" ? "bg-orange" : "bg-long"}
        label={rule?.reason ?? "Daily loss limit"}
        className="mb-3"
      />
      <PresetButtons
        options={[
          { label: "2%", value: 0.02 },
          { label: "3%", value: 0.03 },
          { label: "5%", value: 0.05 },
        ]}
        current={settings.daily_loss_limit_pct}
        onSelect={(v) => update("daily_loss_limit_pct", v)}
        saving={saving}
      />
      <RuleReason rules={rules} ruleKey="daily_loss_limit" />
      {sectionError === "daily_loss_limit_pct" && <SectionError />}
    </RiskSection>
  );
}

function MaxExposureSection({ settings, state, rules, update, saving, sectionError }: {
  settings: RiskSettings; state: RiskState; rules: RiskRule[];
  update: (field: string, value: number | null) => void; saving: boolean; sectionError: string | null;
}) {
  const status = statusFor(rules, "max_exposure");
  const style = STATUS_STYLES[status];
  const usagePct = settings.max_exposure_pct > 0
    ? Math.min(state.exposure_pct / settings.max_exposure_pct * 100, 100)
    : 0;
  const rule = getRule(rules, "max_exposure");

  return (
    <RiskSection title="Max Exposure" status={status}>
      <div className={`font-headline text-2xl font-bold tabular-nums mb-1 ${style.text}`}>
        {(state.exposure_pct * 100).toFixed(0)}% / {(settings.max_exposure_pct * 100).toFixed(0)}%
      </div>
      <ProgressBar
        value={usagePct}
        color={status === "BLOCKED" ? "bg-error" : status === "WARNING" ? "bg-orange" : "bg-long"}
        label={rule?.reason ?? "Max exposure"}
        className="mb-3"
      />
      <PresetButtons
        options={[
          { label: "100%", value: 1.0 },
          { label: "150%", value: 1.5 },
          { label: "200%", value: 2.0 },
        ]}
        current={settings.max_exposure_pct}
        onSelect={(v) => update("max_exposure_pct", v)}
        saving={saving}
        compare={(a, b) => Math.abs(a - b) < 0.001}
      />
      <RuleReason rules={rules} ruleKey="max_exposure" />
      {sectionError === "max_exposure_pct" && <SectionError />}
    </RiskSection>
  );
}

function CooldownSection({ settings, state, rules, update, saving, sectionError }: {
  settings: RiskSettings; state: RiskState; rules: RiskRule[];
  update: (field: string, value: number | null) => void; saving: boolean; sectionError: string | null;
}) {
  const cooldownRule = getRule(rules, "cooldown");
  const cooldownMinutes = settings.cooldown_after_loss_minutes;

  // Compute remaining seconds for countdown
  let initialRemaining = 0;
  if (cooldownMinutes && state.last_sl_hit_at) {
    const elapsed = (Date.now() - Date.parse(state.last_sl_hit_at)) / 1000;
    initialRemaining = Math.max(0, cooldownMinutes * 60 - elapsed);
  }

  const [remaining, setRemaining] = useState(initialRemaining);

  useEffect(() => {
    if (cooldownMinutes && state.last_sl_hit_at) {
      const elapsed = (Date.now() - Date.parse(state.last_sl_hit_at)) / 1000;
      setRemaining(Math.max(0, cooldownMinutes * 60 - elapsed));
    } else {
      setRemaining(0);
    }
  }, [cooldownMinutes, state.last_sl_hit_at]);

  const timerActive = remaining > 0;

  useEffect(() => {
    if (!timerActive) return;
    const id = setInterval(() => {
      setRemaining((r) => {
        const next = r - 1;
        return next <= 0 ? 0 : next;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [timerActive]);
  const displayStatus: Status = timerActive ? "WARNING" : "OK";
  const displayStyle = STATUS_STYLES[displayStatus];

  const mins = Math.floor(remaining / 60);
  const secs = Math.floor(remaining % 60);
  const timerText = timerActive
    ? `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : "Inactive";

  const progressPct = cooldownMinutes && cooldownMinutes > 0
    ? Math.min(remaining / (cooldownMinutes * 60) * 100, 100)
    : 0;
  const progressRule = cooldownRule ?? { reason: "Loss cooldown" };

  return (
    <RiskSection title="Loss Cooldown" status={displayStatus}>
      <div className="flex items-center gap-2 mb-1">
        {timerActive && (
          <span className="w-2 h-2 rounded-full bg-orange animate-pulse motion-reduce:animate-none" />
        )}
        <span className={`font-headline text-2xl font-bold tabular-nums ${displayStyle.text}`}>
          {timerText}
        </span>
      </div>
      {cooldownMinutes && (
        <ProgressBar
          value={progressPct}
          color={timerActive ? "bg-orange" : "bg-long"}
          label={progressRule.reason}
          className="mb-3"
        />
      )}
      <PresetButtons
        options={[
          { label: "Off", value: 0 },
          { label: "15m", value: 15 },
          { label: "30m", value: 30 },
          { label: "60m", value: 60 },
        ]}
        current={cooldownMinutes ?? 0}
        onSelect={(v) => update("cooldown_after_loss_minutes", v === 0 ? null : v)}
        saving={saving}
        compare={(a, b) => a === b}
      />
      {sectionError === "cooldown_after_loss_minutes" && <SectionError />}
    </RiskSection>
  );
}
