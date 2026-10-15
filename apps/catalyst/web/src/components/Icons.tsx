// Line icons, drawn inline so the UI has no icon dependency.
import type { ReactNode } from "react";

function Icon({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const FileIcon = ({ size }: { size?: number }) => (
  <Icon size={size}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 13h6M9 17h4" />
  </Icon>
);

export const HistoryIcon = ({ size }: { size?: number }) => (
  <Icon size={size}>
    <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
    <path d="M3 3v5h5M12 7v5l3 2" />
  </Icon>
);

export const CodeIcon = ({ size }: { size?: number }) => (
  <Icon size={size}>
    <path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" />
  </Icon>
);

export const GearIcon = ({ size }: { size?: number }) => (
  <Icon size={size}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </Icon>
);

export const UploadCloudIcon = ({ size = 40 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M7 18a4.5 4.5 0 0 1-.9-8.9A6 6 0 0 1 17.6 8 4 4 0 0 1 18 18" />
    <path d="M12 12v8M9 15l3-3 3 3" />
  </Icon>
);

export const UploadIcon = ({ size }: { size?: number }) => (
  <Icon size={size}>
    <path d="M12 15V4M8 8l4-4 4 4M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
  </Icon>
);

export const SlidersIcon = ({ size }: { size?: number }) => (
  <Icon size={size}>
    <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" />
    <circle cx="16" cy="6" r="2" />
    <circle cx="10" cy="12" r="2" />
    <circle cx="18" cy="18" r="2" />
  </Icon>
);

export const ResetIcon = ({ size = 16 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M3 12a9 9 0 1 0 2.6-6.4L3 8" />
    <path d="M3 3v5h5" />
  </Icon>
);

export const CubeIcon = ({ size = 18 }: { size?: number }) => (
  <Icon size={size}>
    <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z" />
    <path d="m4 7.5 8 4.5 8-4.5M12 12v9" />
  </Icon>
);

export const ScanTextIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 12h6M9 16h3" />
  </Icon>
);

export const GlobeIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
  </Icon>
);

export const ImageIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <circle cx="9" cy="10" r="1.8" />
    <path d="m21 16-5-5-9 9" />
  </Icon>
);

export const TableIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 10h18M3 15h18M9 4v16M15 4v16" />
  </Icon>
);

export const PagesIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <rect x="7" y="3" width="13" height="16" rx="2" />
    <path d="M4 7v12a2 2 0 0 0 2 2h10M11 8h5M11 12h5" />
  </Icon>
);

export const SparkleIcon = ({ size = 20 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" />
  </Icon>
);

export const ArrowRightIcon = ({ size = 18 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Icon>
);

export const CheckIcon = ({ size = 14 }: { size?: number }) => (
  <Icon size={size}>
    <path d="m5 12 5 5 9-10" />
  </Icon>
);

export const MarkdownIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M8.5 17v-4l1.75 2 1.75-2v4M15 13v4m-1.5-1.5L15 17l1.5-1.5" />
  </Icon>
);

export const BracesIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M8 4H7a2 2 0 0 0-2 2v4l-2 2 2 2v4a2 2 0 0 0 2 2h1M16 4h1a2 2 0 0 1 2 2v4l2 2-2 2v4a2 2 0 0 1-2 2h-1" />
  </Icon>
);

export const TextLinesIcon = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 12h6M9 15h6M9 18h4" />
  </Icon>
);

/** Small coloured file-type badges for the "Supported formats" row. */
export function FormatBadge({ kind }: { kind: "pdf" | "word" | "excel" | "ppt" | "image" | "html" | "text" }) {
  const label = { pdf: "PDF", word: "W", excel: "X", ppt: "P", image: "", html: "</>", text: "TXT" }[kind];
  return (
    <span className={`format-badge badge-${kind}`} aria-hidden="true">
      {kind === "image" ? <ImageIcon size={14} /> : label}
    </span>
  );
}
