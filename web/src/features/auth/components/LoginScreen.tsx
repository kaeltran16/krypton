import { useState, useEffect, useRef, useCallback } from "react";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";

interface LoginScreenProps {
  onLogin: (idToken: string) => Promise<void>;
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const googleLoadedRef = useRef(false);
  const loginInProgress = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const handleCredentialResponse = useCallback(
    async (response: { credential: string }) => {
      if (loginInProgress.current) return;
      loginInProgress.current = true;
      setError(null);
      try {
        await onLogin(response.credential);
      } catch {
        setError("Access denied. Contact an administrator.");
        loginInProgress.current = false;
      }
    },
    [onLogin],
  );

  useEffect(() => {
    if (googleLoadedRef.current) return;
    googleLoadedRef.current = true;

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      const g = (window as any).google.accounts.id;
      g.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
      });
      // Render Google's own sign-in button (reliable, works even when One Tap is suppressed)
      if (googleBtnRef.current) {
        g.renderButton(googleBtnRef.current, {
          type: "standard",
          theme: "filled_black",
          size: "large",
          width: 280,
          text: "continue_with",
        });
      }
    };
    document.head.appendChild(script);
  }, [handleCredentialResponse]);

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center bg-[#0a0f14] relative overflow-hidden">
      {/* Grid background */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(rgba(105,218,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(105,218,255,0.03) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      {/* Ambient glow */}
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] rounded-full bg-[radial-gradient(circle,rgba(0,207,252,0.08)_0%,transparent_70%)] pointer-events-none" />

      <div className="relative z-10 w-[320px] flex flex-col items-center gap-10">
        {/* Brand */}
        <div className="flex flex-col items-center gap-3">
          <div className="w-14 h-14 rounded bg-gradient-to-br from-[#00cffc] to-[#69daff] flex items-center justify-center font-mono font-bold text-2xl text-[#0a0f14] shadow-[0_0_24px_rgba(0,207,252,0.15)]">
            K
          </div>
          <span className="font-mono text-[1.75rem] font-bold tracking-[0.15em] text-[#e7ebf3]">
            KRYPTON
          </span>
          <span className="font-mono text-[0.6875rem] text-[#71767d] tracking-[0.08em]">
            SIGNAL ENGINE v2.0
          </span>
        </div>

        {/* Login card */}
        <div className="w-full glass-card rounded p-8 flex flex-col gap-6">
          <div className="text-center">
            <h2 className="text-base font-semibold text-[#e7ebf3] mb-1">
              Authenticate
            </h2>
            <p className="text-[0.8125rem] text-[#71767d]">
              Authorized operators only
            </p>
          </div>

          <div className="flex justify-center">
            <div ref={googleBtnRef} />
          </div>

          {/* Error message */}
          {error && (
            <p className="text-center text-[0.8125rem] text-[#F6465D]">
              {error}
            </p>
          )}

          {/* Divider */}
          <div className="flex items-center gap-4">
            <div className="flex-1 h-px bg-[rgba(67,72,79,0.3)]" />
            <span className="font-mono text-[0.625rem] text-[#71767d] tracking-[0.1em]">
              SECURE_AUTH
            </span>
            <div className="flex-1 h-px bg-[rgba(67,72,79,0.3)]" />
          </div>

          {/* Encryption badge */}
          <div className="flex items-center justify-center gap-2 font-mono text-[0.5625rem] text-[#56ef9f] tracking-[0.05em] opacity-60">
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#56ef9f"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            ENCRYPTED SESSION
          </div>
        </div>
      </div>
    </div>
  );
}
