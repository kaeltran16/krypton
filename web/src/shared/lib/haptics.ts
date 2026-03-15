/**
 * Haptic feedback via navigator.vibrate (Android only, no-ops elsewhere).
 * Purely additive — UX never depends on vibration.
 */
export function tryVibrate(pattern: number | number[] = 50): void {
  try {
    navigator?.vibrate?.(pattern);
  } catch {}
}

/** Short tap — tab switch, pull-to-refresh trigger */
export function hapticTap(): void {
  tryVibrate(15);
}

/** Signal arrival pulse */
export function hapticPulse(): void {
  tryVibrate(50);
}

/** Critical alert — double pulse */
export function hapticDoublePulse(): void {
  tryVibrate([50, 50, 50]);
}
