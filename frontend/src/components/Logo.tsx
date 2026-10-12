// Vigil identity: the "watchful V" — a V (verified path of money) under an open eyelid (vigilance) on a mint tile.
// Wordmark: VIGIL in Sora, tracked out. The same mark is the favicon (index.html).
import { useId } from "react";

export function LogoMark({ size = 32 }: { size?: number }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="Vigil" className="logo-mark">
      <defs>
        <linearGradient id={`lg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6eedd2" />
          <stop offset="1" stopColor="#1aa585" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9.5" fill={`url(#lg-${id})`} />
      <path d="M8.2 10.4 Q16 3.6 23.8 10.4" fill="none" stroke="#063a30" strokeWidth="2.1" strokeLinecap="round" opacity="0.9" />
      <path d="M9.4 12.6 L16 24.4 L22.6 12.6" fill="none" stroke="#ffffff" strokeWidth="3.1" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="12.9" r="1.9" fill="#063a30" />
    </svg>
  );
}

export function Logo({ tagline = "Fraud operations", size = 32 }: { tagline?: string | null; size?: number }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className="logo-txt">
        <span className="logo-word">VIGIL</span>
        {tagline && <span className="logo-tag">{tagline}</span>}
      </span>
    </span>
  );
}
