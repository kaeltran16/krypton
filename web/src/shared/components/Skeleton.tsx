interface SkeletonProps {
  height?: string;
  count?: number;
  border?: boolean;
  className?: string;
}

export function Skeleton({
  height = "h-20",
  count = 1,
  border = true,
  className = "",
}: SkeletonProps) {
  const base = [
    height,
    "bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none",
    border ? "border border-outline-variant/10" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (count === 1) return <div className={base} />;

  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={base} />
      ))}
    </>
  );
}
