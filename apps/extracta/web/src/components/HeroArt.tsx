// Documents going in, structured output coming out. Colours come from the theme.
export function HeroArt() {
  return (
    <svg className="hero-art" viewBox="0 0 520 220" aria-hidden="true">
      <defs>
        <filter id="hero-shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="6" stdDeviation="8" floodColor="var(--shadow-color)" floodOpacity="0.18" />
        </filter>
      </defs>

      {/* soft sketch strokes */}
      <path d="M20 190 C 90 120, 140 210, 210 150" stroke="var(--accent-soft-strong)" strokeWidth="10" fill="none" strokeLinecap="round" opacity="0.6" />
      <path d="M40 60 C 70 40, 100 70, 130 50" stroke="var(--accent-soft-strong)" strokeWidth="6" fill="none" strokeLinecap="round" opacity="0.5" />

      {/* text document, back */}
      <g transform="rotate(-6 210 90)" filter="url(#hero-shadow)">
        <rect x="160" y="22" width="110" height="140" rx="10" fill="var(--surface)" stroke="var(--border-strong)" />
        <rect x="178" y="44" width="72" height="7" rx="3.5" fill="var(--hero-line)" />
        <rect x="178" y="60" width="60" height="7" rx="3.5" fill="var(--hero-line)" />
        <rect x="178" y="76" width="66" height="7" rx="3.5" fill="var(--hero-line)" />
      </g>

      {/* PDF card */}
      <g transform="rotate(-10 120 120)" filter="url(#hero-shadow)">
        <rect x="80" y="70" width="86" height="104" rx="10" fill="var(--surface)" stroke="var(--border-strong)" />
        <path
          d="M108 128c8-20 16-34 19-40 3 7-2 21-12 36 14-4 26-3 32 1-10 3-22 2-33-2-6 6-12 10-17 10 0-2 4-5 11-5"
          stroke="#d4442e"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>

      {/* Word badge */}
      <g filter="url(#hero-shadow)">
        <rect x="150" y="118" width="62" height="66" rx="10" fill="var(--surface)" stroke="var(--border-strong)" />
        <rect x="164" y="134" width="34" height="34" rx="6" fill="#2b5fbd" />
        <text x="181" y="158" textAnchor="middle" fontSize="20" fontWeight="700" fill="#fff" fontFamily="Inter, system-ui, sans-serif">
          W
        </text>
      </g>

      {/* image badge */}
      <g transform="rotate(8 230 170)" filter="url(#hero-shadow)">
        <rect x="204" y="146" width="52" height="52" rx="9" fill="#3f8f5a" />
        <rect x="216" y="158" width="28" height="22" rx="3" fill="none" stroke="#fff" strokeWidth="2.5" />
        <path d="m218 177 7-7 5 5 4-3 7 6" stroke="#fff" strokeWidth="2.5" fill="none" strokeLinejoin="round" />
      </g>

      {/* arrow */}
      <path d="M268 88 C 290 110, 310 112, 330 98" stroke="var(--accent)" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path d="M322 90 l10 8 -12 4" stroke="var(--accent)" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" />

      {/* output window */}
      <g transform="rotate(4 430 115)" filter="url(#hero-shadow)">
        <rect x="350" y="20" width="160" height="196" rx="12" fill="var(--surface)" stroke="var(--border-strong)" />
        <rect x="350" y="20" width="160" height="26" rx="12" fill="var(--surface-2)" />
        <circle cx="366" cy="33" r="3.5" fill="var(--hero-line)" />
        <circle cx="378" cy="33" r="3.5" fill="var(--hero-line)" />
        <circle cx="390" cy="33" r="3.5" fill="var(--hero-line)" />
        <path d="m400 66-14 12 14 12M430 66l14 12-14 12M422 62l-12 32" stroke="var(--muted)" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="372" y="112" width="116" height="7" rx="3.5" fill="var(--hero-line)" />
        <rect x="372" y="126" width="92" height="7" rx="3.5" fill="var(--accent-soft-strong)" />
        <rect x="372" y="148" width="116" height="48" rx="4" fill="none" stroke="var(--hero-line)" strokeWidth="2" />
        <path d="M372 164h116M372 180h116M410 148v48M450 148v48" stroke="var(--hero-line)" strokeWidth="2" />
      </g>
    </svg>
  );
}
