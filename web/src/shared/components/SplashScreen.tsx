import { useEffect, useRef, useState } from "react";

export function SplashScreen({ onFinished }: { onFinished?: () => void }) {
  const [exiting, setExiting] = useState(false);
  const onFinishedRef = useRef(onFinished);
  onFinishedRef.current = onFinished;

  useEffect(() => {
    let exitTimer: ReturnType<typeof setTimeout>;
    const timer = setTimeout(() => {
      setExiting(true);
      exitTimer = setTimeout(() => onFinishedRef.current?.(), 500);
    }, 1800);
    return () => { clearTimeout(timer); clearTimeout(exitTimer); };
  }, []);

  return (
    <div
      className={`fixed inset-0 z-[9999] bg-surface flex items-center justify-center overflow-hidden transition-opacity duration-500 ${exiting ? "opacity-0" : "opacity-100"}`}
    >
      {/* Grid background */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(rgba(139,154,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(139,154,255,0.03) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      {/* Ambient glow */}
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[320px] h-[320px] rounded-full pointer-events-none animate-[glow-pulse_3s_ease-in-out_infinite]"
        style={{
          background: "radial-gradient(circle, rgba(139,154,255,0.12) 0%, transparent 70%)",
        }}
      />

      {/* Content */}
      <div className="relative z-10 flex flex-col items-center gap-4">
        {/* Logo mark */}
        <div className="animate-[fade-scale-in_0.6s_ease-out_both] w-14 h-14 rounded bg-gradient-to-br from-primary to-[#6775E0] flex items-center justify-center font-mono font-bold text-2xl text-surface shadow-[0_0_24px_rgba(139,154,255,0.2)]">
          K
        </div>

        {/* Wordmark */}
        <span className="animate-[fade-up_0.5s_ease-out_0.25s_both] font-mono text-[1.75rem] font-bold tracking-[0.15em] text-on-surface">
          KRYPTON
        </span>

        {/* Subtitle */}
        <span className="animate-[fade-up_0.5s_ease-out_0.4s_both] font-mono text-[0.6875rem] text-on-surface-variant tracking-[0.08em]">
          SIGNAL ENGINE v2.0
        </span>

        {/* Loading dots */}
        <div className="flex gap-2 mt-6 animate-[fade-up_0.5s_ease-out_0.6s_both]">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-primary"
              style={{
                animation: `dot-bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
              }}
            />
          ))}
        </div>
      </div>

    </div>
  );
}
