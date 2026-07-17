// sovereign-art.js — original 24×24 currentColor SVG glyphs for Sovereign's buildings and units (drawn
// for this project; nothing sourced from any other game). Colored by CSS per tile type.
const S = (b) => '<svg viewBox="0 0 24 24" aria-hidden="true">' + b + "</svg>";
const F = 'fill="currentColor"', N = 'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';

export const ART = {
  // buildings
  unbuilt:  S(`<path d="M3 18h18" ${N}/><path d="M6 18l2-4h8l2 4" ${N}/><circle cx="9" cy="9" r="1.2" ${F}/><circle cx="15" cy="7" r="1.2" ${F}/>`),
  village:  S(`<path d="M4 20V11l5-4 5 4v9z" ${N}/><path d="M14 20V9l3-2 3 2v11z" ${N}/><rect x="7" y="14" width="3" height="6" ${F}/>`),
  city:     S(`<path d="M3 21V9l4-2v14z" ${N}/><path d="M9 21V5l5-2v18z" ${N}/><path d="M15 21V9l6 3v9z" ${N}/><rect x="11" y="7" width="1.6" height="1.6" ${F}/><rect x="11" y="11" width="1.6" height="1.6" ${F}/>`),
  market:   S(`<path d="M4 9l1-3h14l1 3z" ${N}/><path d="M5 9v10h14V9" ${N}/><path d="M9 19v-5h6v5" ${N}/><circle cx="8" cy="12" r=".9" ${F}/>`),
  farm:     S(`<path d="M3 20h18" ${N}/><path d="M6 20c0-5 2-8 6-8s6 3 6 8" ${N}/><path d="M12 12V6" ${N}/><path d="M12 8c-2-1-4 0-4 0s1 2 4 1zM12 8c2-1 4 0 4 0s-1 2-4 1z" ${F}/>`),
  lab:      S(`<path d="M10 4v6l-4 8a2 2 0 0 0 2 3h8a2 2 0 0 0 2-3l-4-8V4" ${N}/><path d="M9 4h6" ${N}/><circle cx="11" cy="16" r="1" ${F}/><circle cx="14" cy="18" r="1.3" ${F}/>`),
  factory:  S(`<path d="M3 21V11l5 3V11l5 3V8h6v13z" ${N}/><rect x="16" y="4" width="3" height="5" ${F}/><path d="M6 21v-3M11 21v-3M16 18v3" ${N}/>`),
  barracks: S(`<path d="M4 20V10l8-4 8 4v10z" ${N}/><path d="M9 20v-6h6v6" ${N}/><path d="M4 10h16" ${N}/><rect x="10.5" y="15" width="3" height="5" ${F}/>`),
  plant:    S(`<path d="M6 20l3-9h2l-1 5h4l-4 9" ${F}/><path d="M4 6h16M6 6l1-2h10l1 2" ${N}/>`),
  arena:    S(`<ellipse cx="12" cy="12" rx="9" ry="6" ${N}/><ellipse cx="12" cy="12" rx="4" ry="2.5" ${F}/><path d="M3 12v3a9 6 0 0 0 18 0v-3" ${N}/>`),
  base:     S(`<path d="M12 3l8 4v5c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V7z" ${N}/><path d="M12 8v8M8 12h8" ${N}/>`),
  builder:  S(`<path d="M14 4l6 6-3 3-6-6z" ${N}/><path d="M11 7L4 14a2 2 0 0 0 0 3l2 2a2 2 0 0 0 3 0l7-7" ${N}/>`),
  ruin:     S(`<path d="M4 20V9l3 2V7l3 2 1-3 2 4 3-1v9z" ${N}/><path d="M9 20v-4" ${N}/>`),
  // units
  soldier:  S(`<circle cx="12" cy="6" r="2.4" ${N}/><path d="M8 21v-6l-2-2 2-4h6l2 4-2 2v6" ${N}/><path d="M18 8v8" ${N}/>`),
  tank:     S(`<rect x="3" y="13" width="16" height="5" rx="1.4" ${N}/><path d="M6 13v-3h7l3 3" ${N}/><path d="M13 11l7-3" ${N}/><circle cx="6" cy="19" r="1.4" ${F}/><circle cx="16" cy="19" r="1.4" ${F}/>`),
  fighter:  S(`<path d="M2 12l9-1 4-6h2l-2 6 7 1-7 1 2 6h-2l-4-6z" ${N}/>`),
  bunker:   S(`<path d="M4 19V13a8 5 0 0 1 16 0v6z" ${N}/><rect x="10" y="11" width="4" height="3" ${F}/><path d="M4 19h16" ${N}/>`),
  mech:     S(`<rect x="8" y="4" width="8" height="6" rx="1.5" ${N}/><path d="M10 10l-3 5 2 5M14 10l3 5-2 5" ${N}/><circle cx="10.5" cy="7" r=".9" ${F}/><circle cx="13.5" cy="7" r=".9" ${F}/>`),
  agent:    S(`<circle cx="12" cy="9" r="4" ${N}/><path d="M6 21c0-3.5 2.7-6 6-6s6 2.5 6 6" ${N}/><path d="M8 8h8" ${N}/>`),
};
