export function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2 px-1">{title}</h2>
      <div className="bg-surface-container rounded-lg overflow-hidden border border-outline-variant/10">
        {children}
      </div>
    </div>
  );
}
