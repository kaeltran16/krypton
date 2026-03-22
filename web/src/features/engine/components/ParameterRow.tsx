import SourceBadge from "./SourceBadge";
import ParamInfoPopup from "./ParamInfoPopup";

interface Props {
  name: string;
  value: unknown;
  source: "hardcoded" | "configurable";
  last?: boolean;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
}

export default function ParameterRow({ name, value, source, last, descriptions }: Props) {
  const display = Array.isArray(value)
    ? value.join(", ")
    : typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value);

  return (
    <div
      className={`flex items-center justify-between px-3 py-2 ${
        last ? "" : "border-b border-border/50"
      }`}
    >
      <div className="flex items-center gap-1">
        <span className="text-xs text-muted">{name}</span>
        <ParamInfoPopup name={name} descriptions={descriptions} />
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-foreground">{display}</span>
        <SourceBadge source={source} />
      </div>
    </div>
  );
}
