export function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative min-h-[44px] min-w-[44px] flex items-center justify-center flex-shrink-0
        focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded
        ${disabled ? "opacity-50" : ""}`}
    >
      <span className={`w-10 h-5 rounded-full transition-colors flex items-center px-1 ${
        checked ? "bg-tertiary-container/20" : "bg-surface-container-highest"
      }`}>
        <span className={`w-3 h-3 rounded-full transition-all ${
          checked
            ? "bg-tertiary-dim shadow-[0_0_8px_rgba(86,239,159,0.5)] ml-auto"
            : "bg-outline"
        }`} />
      </span>
    </button>
  );
}
