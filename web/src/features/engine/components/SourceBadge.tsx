interface Props {
  source: "hardcoded" | "configurable";
}

export default function SourceBadge({ source }: Props) {
  if (source !== "configurable") return null;

  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/15 text-green-400">
      c
    </span>
  );
}
