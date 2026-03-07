import { useEffect, useRef } from "react";

interface Props {
  pair: string;
  timeframe: string;
  studies?: string[];
}

const TF_MAP: Record<string, string> = {
  "15m": "15",
  "1h": "60",
  "4h": "240",
  "1D": "D",
};

export function CandlestickChart({ pair, timeframe, studies = [] }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML = "";
    if (!pair) return;

    const symbol = `OKX:${pair.replace("-USDT-SWAP", "USDT")}.P`;
    const interval = TF_MAP[timeframe] ?? "60";

    const config: Record<string, unknown> = {
      autosize: true,
      symbol,
      interval,
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      backgroundColor: "#12161C",
      gridColor: "rgba(31, 41, 55, 0.5)",
      hide_top_toolbar: true,
      hide_legend: true,
      hide_side_toolbar: true,
      allow_symbol_change: false,
      save_image: false,
      calendar: false,
      support_host: "https://www.tradingview.com",
    };

    if (studies.length > 0) {
      config.studies = studies;
    }

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.type = "text/javascript";
    script.textContent = JSON.stringify(config);

    const wrapper = document.createElement("div");
    wrapper.className = "tradingview-widget-container";
    wrapper.style.height = "100%";
    wrapper.style.width = "100%";

    const inner = document.createElement("div");
    inner.className = "tradingview-widget-container__widget";
    inner.style.height = "100%";
    inner.style.width = "100%";

    wrapper.appendChild(inner);
    wrapper.appendChild(script);
    container.appendChild(wrapper);

    return () => {
      container.innerHTML = "";
    };
  }, [pair, timeframe, studies]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
