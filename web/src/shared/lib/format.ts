const priceFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const smallPriceFormatter = new Intl.NumberFormat("en-US", {
  minimumSignificantDigits: 3,
  maximumSignificantDigits: 5,
});

export function formatPrice(price: number): string {
  if (price === 0) return "0.00";
  if (Math.abs(price) < 1) return smallPriceFormatter.format(price);
  return priceFormatter.format(price);
}

export function formatScore(score: number): string {
  if (score > 0) return `+${score}`;
  return String(score);
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}
