/**
 * Colour-scheme palettes for the animated hero canvas (beachballs, galaxies,
 * wavefronts, seam) and the imprint block-print grounds.
 *
 * The live site uses `SCHEMES.alt2` — the homepage hero is passed it explicitly
 * (`index.astro`), and the matching DOM chrome (purple band, violet accents,
 * lavender text) is baked straight into `tokens.css`. `default` reproduces the
 * original navy/teal constants, so any component handed `SCHEMES.default` (or no
 * palette) renders as the pre-redesign site did — the imprint relies on this to
 * keep its original warm colours.
 *
 * `primary` / `alt1` are earlier trial palettes kept for reference; every hue a
 * scheme owns is a single field below, so a role can be re-cast by swapping two
 * values. (These fed a `/palette/` preview bench that has since been removed.)
 */

export type RGB = [number, number, number];

export interface HeroPalette {
  /** beachball compressional (filled) lobes — the primary "figure" ink */
  comp: RGB;
  /** beachball dilatational (empty) lobes — a light/cream so balls read on the ground */
  dil: RGB;
  /** beachball rim / outline — a dark ink */
  ink: RGB;
  /** the dominant galaxy-field colour (~90% of ellipses) */
  galaxyMain: RGB;
  /** the accent galaxy colour (~8%) — shared with the seismic accents below */
  galaxyAccent: RGB;
  /** the rare "pop" galaxy colour (~2%) */
  galaxyRare: RGB;
  /** light glyph ink: dot lattice (quiet), S-wavefront rings, station triangle */
  light: RGB;
  /** bright accent ink: dot lattice (excited), P-wavefront rings, the seam trace */
  accent: RGB;
  /** muted label ink (the station's "HERO · Z" caption) */
  station: RGB;
  /** imprint block-print grounds (plate re-inks per strand; band is the divider) */
  imprint: {
    calico: string; // seismology plate ground
    meadow: string; // cosmology plate ground
    wave: string; // signals plate ground
    /** motif inks printed on the grounds (cream + dark, as the real papers) */
    cream: RGB;
    darkInk: RGB;
    /** the quiet full-width band divider (ground + ink css strings) */
    bandGround: string;
    bandInk: string;
  };
}

export type SchemeName = 'default' | 'primary' | 'alt1' | 'alt2';

/** Today's live constants — passing this must not change any pixel. */
const DEFAULT: HeroPalette = {
  comp: [47, 168, 163],
  dil: [238, 241, 251],
  ink: [10, 16, 36],
  galaxyMain: [238, 241, 251],
  galaxyAccent: [79, 214, 208],
  galaxyRare: [255, 111, 156],
  light: [238, 241, 251],
  accent: [79, 214, 208],
  station: [154, 166, 200],
  imprint: {
    calico: '#9fa03c',
    meadow: '#27607a',
    wave: '#a84a37',
    cream: [242, 236, 217],
    darkInk: [38, 43, 69],
    bandGround: '#f4f0e4',
    bandInk: 'rgba(159,160,60,0.5)',
  },
};

/**
 * PRIMARY — the user's main proposal.
 * cosmos purple #340059 · beachballs + galaxies salmon #d99e73 ·
 * minor elements / dividers sage #9cb29e.
 */
const PRIMARY: HeroPalette = {
  comp: [217, 158, 115], // salmon
  dil: [242, 228, 213], // warm cream (keeps balls legible on purple)
  ink: [26, 7, 51], // deep cosmos ink
  galaxyMain: [217, 158, 115], // salmon galaxy field
  galaxyAccent: [156, 178, 158], // sage
  galaxyRare: [240, 210, 180], // pale salmon pop
  light: [242, 228, 213], // cream
  accent: [156, 178, 158], // sage seam / P-wave
  station: [156, 178, 158], // sage label
  imprint: {
    calico: '#7a5a86', // muted plum ground
    meadow: '#4a2c63', // deep violet ground
    wave: '#8c5a3c', // warm terracotta ground
    cream: [242, 228, 213],
    darkInk: [26, 7, 51],
    bandGround: '#e4ece0', // pale sage
    bandInk: 'rgba(156,178,158,0.6)', // sage divider
  },
};

/**
 * ALT 1 — yellow / orange on purple, slate as the dark.
 * #f2ff26 yellow · #ff7340 orange · #340059 purple · #1b3644 slate.
 */
const ALT1: HeroPalette = {
  comp: [255, 115, 64], // orange beachballs
  dil: [245, 240, 220], // pale cream
  ink: [27, 54, 68], // slate outline
  galaxyMain: [255, 115, 64], // orange galaxy field
  galaxyAccent: [242, 255, 38], // yellow accent
  galaxyRare: [255, 240, 120], // pale yellow pop
  light: [245, 240, 220], // pale cream
  accent: [242, 255, 38], // yellow seam / P-wave
  station: [180, 196, 150], // muted olive-yellow label
  imprint: {
    calico: '#c65a2a', // burnt orange ground
    meadow: '#1b3644', // slate ground
    wave: '#a88a1e', // dark yellow ground
    cream: [245, 240, 220],
    darkInk: [27, 54, 68],
    bandGround: '#efe9d0', // pale straw
    bandInk: 'rgba(255,115,64,0.5)', // orange divider
  },
};

/**
 * ALT 2 — red / lavender / violet on purple.
 * #d60036 red beachballs · #b8b8ff lavender text · #9c52f2 brighter violet
 * accents · #340059 purple ground.
 */
const ALT2: HeroPalette = {
  comp: [214, 0, 54], // red beachballs
  dil: [230, 230, 255], // pale lavender
  ink: [26, 7, 51], // deep cosmos ink
  // galaxy field: lavender dominant, with blue AND red mixed in (user request)
  galaxyMain: [184, 184, 255], // lavender galaxy field
  galaxyAccent: [61, 107, 255], // blue galaxies
  galaxyRare: [214, 0, 54], // red galaxies
  light: [230, 230, 255], // pale lavender
  accent: [156, 82, 242], // brighter violet — seam / P-wave / seismic accents
  station: [184, 184, 255], // lavender label
  // imprint block-print keeps the ORIGINAL warm colours (user preferred them)
  imprint: DEFAULT.imprint,
};

export const SCHEMES: Record<SchemeName, HeroPalette> = {
  default: DEFAULT,
  primary: PRIMARY,
  alt1: ALT1,
  alt2: ALT2,
};

/** css `rgba(r,g,b,a)` from an RGB tuple and an alpha in [0,1]. */
export function rgba(c: RGB, a: number): string {
  return `rgba(${c[0]},${c[1]},${c[2]},${a.toFixed(3)})`;
}
