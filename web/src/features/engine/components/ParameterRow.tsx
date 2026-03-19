import SourceBadge from "./SourceBadge";

interface Props {
  name: string;
  value: unknown;
  source: "hardcoded" | "configurable";
  last?: boolean;
}

export default function ParameterRow({ name, value, source, last }: Props) {
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
      <span className="text-xs text-muted">{name}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-foreground">{display}</span>
        <SourceBadge source={source} />
      </div>
    </div>
  );
}
