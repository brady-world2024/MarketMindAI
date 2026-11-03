import type { CSSProperties } from "react";

type IconName = "research" | "library" | "arrow" | "document" | "evidence" | "review" | "settings" | "clock" | "refresh" | "chevron";

const paths: Record<IconName, string> = {
  research: "M4 17V7m5 10V4m5 13v-6m5 6V2M2 21h20",
  library: "M4 4h5v16H4zM11 4h4v16h-4zM17 5l3-1 4 15-3 1z",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  document: "M14 3H5v18h14V8zm0 0v6h5M8 13h8m-8 4h6",
  evidence: "M9 4H4v16h5m6-16h5v16h-5M8 12l3 3 5-6",
  review: "M12 3l8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6zm-4 9 3 3 5-6",
  settings: "M4 7h16M4 17h16M8 4v6m8 4v6",
  clock: "M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  refresh: "M20 8a8 8 0 1 0 0 8m0-13v5h-5",
  chevron: "M9 5l7 7-7 7",
};

export function WorkbenchIcon({ name, size = 18, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>
    <path d={paths[name]} />
  </svg>;
}
