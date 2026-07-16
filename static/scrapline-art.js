// scrapline-art.js — ORIGINAL inline SVG emblems for every Scrapline item (small geometric glyphs drawn
// for this project; nothing sourced from any other game). 24×24 viewBox, currentColor — the tile's tag
// palette colors them via CSS.
const S = (body) => '<svg viewBox="0 0 24 24" aria-hidden="true">' + body + "</svg>";
const F = 'fill="currentColor"', N = 'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';

export const ART = {
  shiv: S(`<path d="M5 19l9-9 3 3-9 9H5z" ${N}/><path d="M14 10l4-6 2 2-6 4z" ${F}/>`),
  scrappistol: S(`<path d="M4 8h13v4h-5l-1 5H8l1-5H4z" ${N}/><path d="M17 9h3v2h-3z" ${F}/>`),
  blowtorch: S(`<path d="M5 9h8v5H5z" ${N}/><path d="M13 11h2" ${N}/><path d="M15 11c3-2 5-1.5 6 .5-1.6.3-2.4 1.4-3.4 2.5-1-.4-2-1.6-2.6-3z" ${F}/>`),
  buckler: S(`<path d="M12 4l7 2.5v5c0 4.2-2.8 7-7 8.5-4.2-1.5-7-4.3-7-8.5v-5z" ${N}/><circle cx="12" cy="11" r="2.2" ${F}/>`),
  patchkit: S(`<rect x="4" y="7" width="16" height="11" rx="2" ${N}/><path d="M10.5 10.5h3v2h2v3h-2v2h-3v-2h-2v-3h2z" ${F}/>`),
  grindstone: S(`<circle cx="10" cy="13" r="6" ${N}/><circle cx="10" cy="13" r="1.4" ${F}/><path d="M15 8l5-4" ${N}/>`),
  powderpack: S(`<path d="M7 8h10v11a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 7 19z" ${N}/><path d="M9 8V6h6v2" ${N}/><circle cx="10.5" cy="13" r=".9" ${F}/><circle cx="13.5" cy="15.5" r=".9" ${F}/><circle cx="11.5" cy="17.5" r=".9" ${F}/>`),
  ballast: S(`<path d="M4 17h16v3H4z" ${F}/><path d="M6 17l1.5-5h9L18 17" ${N}/><path d="M9 12l1-4h4l1 4" ${N}/>`),
  buzzsaw: S(`<circle cx="12" cy="12" r="5" ${N}/><path d="M12 3l1.5 3-3 .2zM21 12l-3 1.5-.2-3zM12 21l-1.5-3 3-.2zM3 12l3-1.5.2 3zM18.4 5.6l-1 3.2-2-2.2zM18.4 18.4l-3.2-1 2.2-2zM5.6 18.4l1-3.2 2 2.2zM5.6 5.6l3.2 1-2.2 2z" ${F}/>`),
  nailrifle: S(`<path d="M3 11h14l4-2v5l-4-1H8l-1 4H5l1-4H3z" ${N}/>`),
  arcwelder: S(`<path d="M5 15V7h4l2 4h5" ${N}/><path d="M16 11l3-3M16 11l4 1M16 11l1 4" ${N}/><path d="M5 15a3 3 0 1 0 6 0 3 3 0 0 0-6 0z" ${N}/>`),
  tarsprayer: S(`<path d="M4 10h8v6H4z" ${N}/><path d="M12 12h3" ${N}/><path d="M16.5 10.5c1 2 2.5 3 4.5 3-1.5 2-3.5 2.5-5.5 1.5" ${F}/><circle cx="19" cy="17.5" r="1.1" ${F}/>`),
  boilerplate: S(`<rect x="5" y="5" width="14" height="14" rx="2" ${N}/><circle cx="8" cy="8" r=".9" ${F}/><circle cx="16" cy="8" r=".9" ${F}/><circle cx="8" cy="16" r=".9" ${F}/><circle cx="16" cy="16" r=".9" ${F}/><path d="M5 12h14" ${N}/>`),
  coolantpump: S(`<path d="M12 4c3.5 4 5.5 7 5.5 10a5.5 5.5 0 1 1-11 0C6.5 11 8.5 8 12 4z" ${N}/><path d="M9.5 14.5a2.5 2.5 0 0 0 2.5 2.5" ${N}/>`),
  twinslingers: S(`<path d="M4 7h7v3H8l-1 4H5l1-4H4zM13 14h7v3h-3l-1 4h-2l1-4h-2z" ${N}/>`),
  staticcoil: S(`<path d="M6 18V8a3 3 0 0 1 6 0v8a3 3 0 0 0 6 0V6" ${N}/><path d="M18 4l-1.5 2.5h3L18 9" ${F}/>`),
  rivetkit: S(`<path d="M5 8l7-4 7 4v8l-7 4-7-4z" ${N}/><circle cx="12" cy="12" r="2.4" ${F}/>`),
  capacitor: S(`<path d="M4 12h5M15 12h5" ${N}/><path d="M9 6v12M15 8v8" ${N}/>`),
  accelerant: S(`<rect x="6" y="8" width="12" height="11" rx="2" ${N}/><path d="M10 8V5h4v3" ${N}/><path d="M12 11c1.5 1.3 2 2.6 1 3.7-.7.8-2.1.8-2.6-.1-.5-1 .1-2.4 1.6-3.6z" ${F}/>`),
  pipecleaver: S(`<path d="M5 20l7-7" ${N}/><path d="M11 5l8 2-2 8-6-2-2-6z" ${F}/>`),
  junkmortar: S(`<path d="M6 19h12" ${N}/><path d="M8 19l2-5 8-8c1.6 1.6 1.6 3.4 0 5l-6 6z" ${N}/><circle cx="17" cy="7" r="1.2" ${F}/>`),
  rebarlance: S(`<path d="M4 20L17 7" ${N}/><path d="M15 4l5 5-1.5 1.5L13.5 5.5z" ${F}/><path d="M8 13l3 3M11 10l3 3" ${N}/>`),
  teslafist: S(`<path d="M6 13V8h9a3 3 0 0 1 3 3v2a5 5 0 0 1-5 5H9a3 3 0 0 1-3-3z" ${N}/><path d="M12 3l-2 4h4l-2 4" ${F}/>`),
  furnaceheart: S(`<path d="M12 20c-4-2.6-6-5.2-6-8a6 6 0 0 1 12 0c0 2.8-2 5.4-6 8z" ${N}/><path d="M12 8c1.8 1.6 2.4 3.1 1.2 4.4-.8.9-2.4.8-3-.2-.7-1.2 0-2.8 1.8-4.2z" ${F}/>`),
  mirrorguard: S(`<path d="M12 4l7 2.5v5c0 4.2-2.8 7-7 8.5-4.2-1.5-7-4.3-7-8.5v-5z" ${N}/><path d="M8.5 13.5l6-6" ${N}/><path d="M10.5 16l5-5" ${N} opacity=".6"/>`),
  welddrone: S(`<circle cx="12" cy="11" r="4" ${N}/><path d="M8.2 8.2 5 5M15.8 8.2 19 5M5 5h3M5 5v3M19 5h-3M19 5v3" ${N}/><path d="M11 15.5h2l-.4 3h-1.2z" ${F}/>`),
  overclock: S(`<rect x="7" y="7" width="10" height="10" rx="1.6" ${N}/><path d="M9 4v2M15 4v2M9 18v2M15 18v2M4 9h2M4 15h2M18 9h2M18 15h2" ${N}/><path d="M12 9.5v3l2 1.5" ${N}/>`),
  magnetrig: S(`<path d="M7 4v7a5 5 0 0 0 10 0V4" ${N}/><path d="M6 4h3v4H6zM15 4h3v4h-3z" ${F}/>`),
};
