// stormhold-art.js — ORIGINAL inline SVG emblems for every Stormhold card (one small geometric glyph per
// card, drawn for this project — same pattern as chess.js's piece silhouettes). All glyphs share a
// 24×24 viewBox and draw in currentColor, so the tile's type palette colors them via CSS.
const S = (body) => '<svg viewBox="0 0 24 24" aria-hidden="true">' + body + "</svg>";
const F = 'fill="currentColor"', N = 'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';

export const ART = {
  copper: S(`<circle cx="12" cy="12" r="7.5" ${N}/><circle cx="12" cy="12" r="3" ${F}/>`),
  silver: S(`<circle cx="12" cy="12" r="7.5" ${N}/><path d="M8.5 12h7M12 8.5v7" ${N}/>`),
  gold: S(`<circle cx="12" cy="12" r="7.5" ${N}/><path d="M12 7.5l1.4 2.9 3.1.4-2.3 2.2.6 3.1-2.8-1.5-2.8 1.5.6-3.1-2.3-2.2 3.1-.4z" ${F}/>`),
  homestead: S(`<path d="M4 12l8-6 8 6" ${N}/><path d="M6.5 11.5V19h11v-7.5" ${N}/><path d="M10.5 19v-4.5h3V19" ${F}/>`),
  valley: S(`<path d="M3 17l5-8 4 6 3-4.5L21 17z" ${N}/><circle cx="17" cy="7" r="2" ${N}/>`),
  citadel: S(`<path d="M5 20V9h3V6h2v3h4V6h2v3h3v11z" ${N}/><path d="M10.5 20v-4h3v4" ${F}/>`),
  blight: S(`<path d="M12 4c4 3 5 7 3 10.5S8 18 6.5 15 8 7 12 4z" ${N}/><circle cx="11" cy="11" r="1.3" ${F}/><circle cx="14.5" cy="14.5" r="1" ${F}/>`),
  winnow: S(`<path d="M5 18c5 1 9-1 11-5" ${N}/><path d="M16 13l3-5M14 11l1-6M11.5 10L9 5" ${N}/><circle cx="17.5" cy="17.5" r="1.2" ${F}/><circle cx="20" cy="15" r="1" ${F}/>`),
  purifier: S(`<path d="M6 19h12M8 19V9h8v10" ${N}/><path d="M12 5c1.8 1.6 2.4 3.2 1.2 4.6-.8 1-2.6 1-3.2-.2C9.4 8 10.4 6.4 12 5z" ${F}/>`),
  windbreak: S(`<path d="M5 19V9M12 19V9M19 19V9" ${N}/><path d="M4 12h16M4 16h16" ${N}/><path d="M3 6c3 1.6 6 1.6 9 0s6-1.6 9 0" ${N}/>`),
  undertow: S(`<path d="M4 9c2.5 2 5.5 2 8 0s5.5-2 8 0" ${N}/><path d="M4 14c2.5 2 5.5 2 8 0s5.5-2 8 0" ${N}/><path d="M12 20V12m0 8-2.6-2.6M12 20l2.6-2.6" ${N}/>`),
  hawker: S(`<path d="M5 10h14l-1.6 9H6.6z" ${N}/><path d="M8 10c0-3 1.6-5 4-5s4 2 4 5" ${N}/><circle cx="12" cy="14.5" r="2" ${F}/>`),
  whirlwind: S(`<path d="M19 6c-4-2-10-2-13 1s-1 8 3 8c3 0 4.5-3 2.5-4.5S7 10 7.5 12" ${N}/><path d="M6 19.5h5" ${N}/>`),
  waystation: S(`<path d="M12 21V4" ${N}/><path d="M12 5h8l-2 2.5L20 10h-8" ${F}/><path d="M12 12H5l1.8 2.2L5 16.5h7" ${N}/>`),
  foundry: S(`<path d="M4 17h16v2.5H4z" ${F}/><path d="M7 17v-3h10v3" ${N}/><path d="M9 14V9l-3-3h12l-3 3v5" ${N}/>`),
  collector: S(`<path d="M6 4h12v16l-3-2-3 2-3-2-3 2z" ${N}/><path d="M9 9h6M9 12.5h6" ${N}/>`),
  terraces: S(`<path d="M4 19h16" ${N}/><path d="M6 19v-3h12v3M8 16v-3h8v3M10 13v-3h4v3" ${N}/><path d="M12 10V6" ${N}/><circle cx="12" cy="5" r="1.4" ${F}/>`),
  raiders: S(`<path d="M6 5l12 12M18 5 6 17" ${N}/><path d="M5 4l3 1-2 2zM19 4l-3 1 2 2zM5 18l3-1-2-2zM19 18l-3-1 2-2z" ${F}/>`),
  smelter: S(`<path d="M6 9h12l-2 9H8z" ${N}/><path d="M8.5 9C8.5 6 10 4.5 12 4.5S15.5 6 15.5 9" ${N}/><path d="M9.5 13c1.6 1.2 3.4 1.2 5 0" ${N}/>`),
  drifter: S(`<path d="M5 19c0-6 3-9 7-9 3 0 4-2 4-5" ${N}/><circle cx="16" cy="4.5" r="1.6" ${F}/><path d="M4 21h5M8 16.5l2 2" ${N}/>`),
  reforge: S(`<path d="M4 8h9v4H4z" ${F}/><path d="M13 10h4" ${N}/><path d="M16 6l4 4-4 4" ${N}/><path d="M8.5 12v7" ${N}/>`),
  scribe: S(`<path d="M17 4c-6 1-9 4-10 10l-2 6 6-2c6-1 9-4 10-10z" ${N}/><path d="M8 16l7-7" ${N}/>`),
  echo: S(`<circle cx="12" cy="12" r="2.2" ${F}/><circle cx="12" cy="12" r="5.5" ${N}/><circle cx="12" cy="12" r="9" ${N} opacity=".55"/>`),
  stormriders: S(`<path d="M13 3 6 13h4l-2 8 8-11h-4z" ${F}/><path d="M17 5l3 3M19 3l2 2" ${N}/>`),
  assembly: S(`<circle cx="7" cy="8" r="2.1" ${F}/><circle cx="17" cy="8" r="2.1" ${F}/><circle cx="12" cy="6" r="2.4" ${F}/><path d="M3.5 19c.6-3.4 1.9-5 3.5-5s2.9 1.6 3.5 5M13.5 19c.6-3.4 1.9-5 3.5-5s2.9 1.6 3.5 5M8.2 17c.7-3.8 2.1-5.6 3.8-5.6s3.1 1.8 3.8 5.6" ${N}/>`),
  jubilee: S(`<path d="M5 4v16" ${N}/><path d="M5 5h13l-3 3.5 3 3.5H5" ${F}/>`),
  observatory: S(`<path d="M5 20a7 7 0 0 1 14 0z" ${N}/><path d="M12 13 18 5" ${N}/><circle cx="19" cy="4" r="1.6" ${F}/><path d="M9 20v-3" ${N}/>`),
  almanac: S(`<path d="M5 5h6a2 2 0 0 1 2 2v12a2 2 0 0 0-2-2H5zM19 5h-6" ${N}/><path d="M13 7a2 2 0 0 1 2-2h4v12h-4a2 2 0 0 0-2 2" ${N}/><circle cx="9" cy="9" r="1" ${F}/>`),
  nightmarket: S(`<path d="M16.5 4a6.5 6.5 0 1 0 4 10.5A7.5 7.5 0 0 1 16.5 4z" ${F}/><circle cx="6" cy="6" r="1" ${F}/><circle cx="8.5" cy="10" r=".8" ${F}/>`),
  refinery: S(`<path d="M9 4h6v4l3 9a3 3 0 0 1-3 4H9a3 3 0 0 1-3-4l3-9z" ${N}/><path d="M8 15h8" ${N}/><circle cx="11" cy="18" r="1" ${F}/><circle cx="14" cy="17.5" r=".8" ${F}/>`),
  skywatch: S(`<path d="M3 12c2.6-4 5.6-6 9-6s6.4 2 9 6c-2.6 4-5.6 6-9 6s-6.4-2-9-6z" ${N}/><circle cx="12" cy="12" r="2.6" ${F}/>`),
  stormcaller: S(`<path d="M7 14a4.5 4.5 0 1 1 .8-8.9A5.5 5.5 0 0 1 18 7a4 4 0 0 1 1 7.9" ${N}/><path d="M13 12l-4 6h3l-1.5 5 4.5-6h-3z" ${F}/>`),
  atelier: S(`<path d="M5 19c0-3 1.5-4.5 3.5-4.5L17 6l1.5 1.5-8.5 8.5C10 18 8 19.5 5 19z" ${N}/><path d="M16 5l3 3 1-1a2.1 2.1 0 0 0-3-3z" ${F}/>`),
};
