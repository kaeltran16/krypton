import type { ParameterSource } from "../types";

interface Props {
  source: ParameterSource;
}

export default function SourceBadge({ source }: Props) {
  if (source === "configurable") {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/15 text-green-400 uppercase tracking-wider">
        tunable
      </span>
    );
  }
  return null;
}
