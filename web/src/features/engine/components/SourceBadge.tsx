interface Props {
  source: "hardcoded" | "configurable";
}

export default function SourceBadge({ source }: Props) {
  const styles =
    source === "configurable"
      ? "bg-green-500/15 text-green-400"
      : "bg-white/8 text-muted";

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${styles}`}>
      {source}
    </span>
  );
}
