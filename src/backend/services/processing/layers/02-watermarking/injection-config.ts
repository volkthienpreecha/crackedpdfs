import type {
  PdfAttackFamily,
  PdfAttackStrength,
} from "@/lib/pdf-benchmark-taxonomy";

export type SpatialRegime =
  | "extreme_off_page"
  | "negative_off_page"
  | "near_margin"
  | "inside_page";

export type RenderingRegime =
  | "invisible_render_mode"
  | "tiny_font"
  | "white_text"
  | "normal_visible";

export type StructuralRegime =
  | "append_new_stream"
  | "prepend_stream"
  | "inject_into_existing_stream";

export type ArtifactRegime = "artifact_wrapped" | "no_artifact";
export type CoordinatesMode = "regime" | "override";

export interface InjectionConfig {
  spatial_regime: SpatialRegime;
  rendering_regime: RenderingRegime;
  structural_regime: StructuralRegime;
  artifact_wrapper: boolean;
  artifact_regime: ArtifactRegime;
  attack_family: PdfAttackFamily;
  attack_strength: PdfAttackStrength;
  font_size: number;
  coordinates: [number, number];
  coordinates_mode: CoordinatesMode;
  render_mode: number;
  color: [number, number, number];
  compatibility_notes: string[];
}

const VALID_SPATIAL_REGIMES = new Set<SpatialRegime>([
  "extreme_off_page",
  "negative_off_page",
  "near_margin",
  "inside_page",
]);

const VALID_RENDERING_REGIMES = new Set<RenderingRegime>([
  "invisible_render_mode",
  "tiny_font",
  "white_text",
  "normal_visible",
]);

const VALID_STRUCTURAL_REGIMES = new Set<StructuralRegime>([
  "append_new_stream",
  "prepend_stream",
  "inject_into_existing_stream",
]);

const VALID_ARTIFACT_REGIMES = new Set<ArtifactRegime>([
  "artifact_wrapped",
  "no_artifact",
]);

const VALID_ATTACK_FAMILIES = new Set<PdfAttackFamily>([
  "plain_single_block",
  "split_text_objects",
  "header_footer_like",
  "near_margin_normal_font",
  "in_page_invisible_text",
  "in_page_white_text",
  "in_page_tiny_text",
  "in_page_split_text_objects",
  "layout_mimicry",
  "semantic_fragmentation",
  "existing_stream_patch",
  "in_page_low_contrast_text",
  "margin_microtext",
  "steganographic_acrostic",
  "microglyph_steganography",
]);

const VALID_ATTACK_STRENGTHS = new Set<PdfAttackStrength>([
  "weak",
  "medium",
  "strong",
]);

const VALID_COORDINATES_MODES = new Set<CoordinatesMode>(["regime", "override"]);

export const SPATIAL_REGIME_COORDINATES: Record<
  SpatialRegime,
  [number, number]
> = {
  extreme_off_page: [10000, 10000],
  // Runtime page-relative logic will use [-W, -H] when mode is "regime".
  negative_off_page: [-1, -1],
  // Runtime page-relative logic will use [W + 10, H / 2] when mode is "regime".
  near_margin: [10, 0.5],
  // Runtime page-relative logic will use [W * 0.5, H * 0.5] when mode is "regime".
  inside_page: [0.5, 0.5],
};

export const RENDERING_REGIME_PRESETS: Record<
  RenderingRegime,
  Pick<InjectionConfig, "render_mode" | "font_size" | "color">
> = {
  invisible_render_mode: {
    render_mode: 3,
    font_size: 12,
    color: [0, 0, 0],
  },
  tiny_font: {
    render_mode: 0,
    font_size: 2,
    color: [0, 0, 0],
  },
  white_text: {
    render_mode: 0,
    font_size: 12,
    color: [1, 1, 1],
  },
  normal_visible: {
    render_mode: 0,
    font_size: 12,
    color: [0, 0, 0],
  },
};

export const DEFAULT_INJECTION_CONFIG: InjectionConfig = {
  spatial_regime: "extreme_off_page",
  rendering_regime: "invisible_render_mode",
  structural_regime: "append_new_stream",
  artifact_wrapper: true,
  artifact_regime: "artifact_wrapped",
  attack_family: "plain_single_block",
  attack_strength: "medium",
  font_size: 12,
  coordinates: [10000, 10000],
  coordinates_mode: "regime",
  render_mode: 3,
  color: [0, 0, 0],
  compatibility_notes: [],
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    if (value.toLowerCase() === "true") return true;
    if (value.toLowerCase() === "false") return false;
  }
  return undefined;
}

function parseCoordinates(value: unknown): [number, number] | undefined {
  if (!Array.isArray(value) || value.length !== 2) return undefined;
  const x = asNumber(value[0]);
  const y = asNumber(value[1]);
  if (x === undefined || y === undefined) return undefined;
  return [x, y];
}

function parseColor(value: unknown): [number, number, number] | undefined {
  if (!Array.isArray(value) || value.length !== 3) return undefined;
  const r = asNumber(value[0]);
  const g = asNumber(value[1]);
  const b = asNumber(value[2]);
  if (r === undefined || g === undefined || b === undefined) return undefined;
  const clamp = (channel: number) => Math.min(1, Math.max(0, channel));
  return [clamp(r), clamp(g), clamp(b)];
}

function cloneInjectionConfig(config: InjectionConfig): InjectionConfig {
  return {
    ...config,
    coordinates: [...config.coordinates],
    color: [...config.color],
    compatibility_notes: [...config.compatibility_notes],
  };
}

const RESOLVED_CONFIG_KEYS: readonly (keyof InjectionConfig)[] = [
  "spatial_regime",
  "rendering_regime",
  "structural_regime",
  "artifact_wrapper",
  "artifact_regime",
  "attack_family",
  "attack_strength",
  "font_size",
  "coordinates",
  "coordinates_mode",
  "render_mode",
  "color",
  "compatibility_notes",
];

export function isResolvedInjectionConfig(input: unknown): input is InjectionConfig {
  if (!isObject(input) || RESOLVED_CONFIG_KEYS.some((key) => !(key in input))) {
    return false;
  }
  if (
    typeof input.artifact_wrapper !== "boolean" ||
    typeof input.font_size !== "number" ||
    typeof input.render_mode !== "number" ||
    !Array.isArray(input.coordinates) ||
    !Array.isArray(input.color) ||
    !Array.isArray(input.compatibility_notes) ||
    input.compatibility_notes.some((note) => typeof note !== "string")
  ) {
    return false;
  }
  try {
    assertResolvedInjectionConfig(input as unknown as InjectionConfig);
    return true;
  } catch {
    return false;
  }
}

/**
 * Resolve a partial injection request into a complete, validated config.
 *
 * Resolution is idempotent: resolveInjectionConfig(resolveInjectionConfig(x))
 * deep-equals resolveInjectionConfig(x). Paper v1 violated this. The ADA layer
 * re-resolved an already resolved config, its page-relative regime anchors
 * (for example [0.5, 0.5]) were re-read as explicit coordinate overrides, and
 * the injector placed them as absolute PDF points at the bottom-left corner.
 * See paper-v1/ERRATA.md.
 */
export function resolveInjectionConfig(input: unknown): InjectionConfig {
  if (isResolvedInjectionConfig(input)) {
    return cloneInjectionConfig(input);
  }

  const base: InjectionConfig = {
    ...DEFAULT_INJECTION_CONFIG,
    coordinates: [...DEFAULT_INJECTION_CONFIG.coordinates],
    color: [...DEFAULT_INJECTION_CONFIG.color],
    compatibility_notes: [],
  };

  if (!isObject(input)) {
    return base;
  }

  const spatial = input.spatial_regime;
  if (
    typeof spatial === "string" &&
    spatial in SPATIAL_REGIME_COORDINATES
  ) {
    base.spatial_regime = spatial as SpatialRegime;
    base.coordinates = [...SPATIAL_REGIME_COORDINATES[base.spatial_regime]];
    base.coordinates_mode = "regime";
  }

  const rendering = input.rendering_regime;
  if (
    typeof rendering === "string" &&
    rendering in RENDERING_REGIME_PRESETS
  ) {
    base.rendering_regime = rendering as RenderingRegime;
    const preset = RENDERING_REGIME_PRESETS[base.rendering_regime];
    base.render_mode = preset.render_mode;
    base.font_size = preset.font_size;
    base.color = [...preset.color];
  }

  const structural = input.structural_regime;
  if (
    structural === "append_new_stream" ||
    structural === "append_stream" ||
    structural === "prepend_stream" ||
    structural === "inject_into_existing_stream"
  ) {
    base.structural_regime =
      structural === "append_stream" ? "append_new_stream" : structural;
  }

  const artifactWrapper = asBoolean(input.artifact_wrapper);
  if (artifactWrapper !== undefined) {
    base.artifact_wrapper = artifactWrapper;
    base.artifact_regime = artifactWrapper
      ? "artifact_wrapped"
      : "no_artifact";
  }

  const attackFamily = input.attack_family;
  if (typeof attackFamily === "string" && VALID_ATTACK_FAMILIES.has(attackFamily as PdfAttackFamily)) {
    base.attack_family = attackFamily as PdfAttackFamily;
  }

  const attackStrength = input.attack_strength;
  if (
    typeof attackStrength === "string" &&
    VALID_ATTACK_STRENGTHS.has(attackStrength as PdfAttackStrength)
  ) {
    base.attack_strength = attackStrength as PdfAttackStrength;
  }

  // Independent overrides (higher precedence than regime presets)
  // Coordinates tagged as regime anchors are page-relative placeholders, not
  // absolute points, so they must never be promoted to an override.
  const coordinates = parseCoordinates(input.coordinates);
  if (coordinates && input.coordinates_mode !== "regime") {
    base.coordinates = coordinates;
    base.coordinates_mode = "override";
  }

  const fontSize = asNumber(input.font_size);
  if (fontSize !== undefined && fontSize > 0) {
    base.font_size = fontSize;
  }

  const renderMode = asNumber(input.render_mode);
  if (renderMode !== undefined) {
    base.render_mode = Math.min(7, Math.max(0, Math.round(renderMode)));
  }

  const color = parseColor(input.color);
  if (color) {
    base.color = color;
  }

  // Compatibility matrix: avoid intentionally visible on-page combinations.
  if (
    base.attack_family !== "near_margin_normal_font" &&
    (base.spatial_regime === "inside_page" ||
      base.spatial_regime === "near_margin") &&
    base.rendering_regime === "normal_visible"
  ) {
    const fallback = RENDERING_REGIME_PRESETS.white_text;
    base.rendering_regime = "white_text";
    base.render_mode = fallback.render_mode;
    base.font_size = fallback.font_size;
    base.color = [...fallback.color];
    base.compatibility_notes.push(
      `Adjusted rendering_regime from normal_visible to white_text for ${base.spatial_regime}.`
    );
  }

  if (base.attack_family === "header_footer_like") {
    if (base.rendering_regime === "normal_visible") {
      const fallback = RENDERING_REGIME_PRESETS.white_text;
      base.rendering_regime = "white_text";
      base.render_mode = fallback.render_mode;
      base.font_size = fallback.font_size;
      base.color = [...fallback.color];
      base.compatibility_notes.push(
        "Adjusted rendering_regime from normal_visible to white_text for header_footer_like."
      );
    }
    if (base.coordinates_mode === "regime") {
      // The injector always anchors this family in the header or footer band,
      // so an off-page or in-page spatial label would be false.
      if (base.spatial_regime !== "near_margin") {
        base.compatibility_notes.push(
          `Adjusted spatial_regime from ${base.spatial_regime} to near_margin for header_footer_like.`
        );
      }
      base.spatial_regime = "near_margin";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.near_margin];
    }
  }

  if (base.attack_family === "near_margin_normal_font") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "near_margin";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.near_margin];
    }
    if (base.rendering_regime !== "normal_visible") {
      const fallback = RENDERING_REGIME_PRESETS.normal_visible;
      base.rendering_regime = "normal_visible";
      base.render_mode = fallback.render_mode;
      base.font_size = Math.max(base.font_size, 9);
      base.color = [...fallback.color];
      base.compatibility_notes.push(
        `Adjusted rendering_regime from ${input.rendering_regime ?? "default"} to normal_visible for near_margin_normal_font.`
      );
    } else {
      base.render_mode = RENDERING_REGIME_PRESETS.normal_visible.render_mode;
      base.font_size = Math.max(base.font_size, 9);
      base.color = [...RENDERING_REGIME_PRESETS.normal_visible.color];
    }
  }

  if (base.attack_family === "in_page_invisible_text") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    const preset = RENDERING_REGIME_PRESETS.invisible_render_mode;
    base.rendering_regime = "invisible_render_mode";
    base.render_mode = preset.render_mode;
    base.font_size = Math.max(base.font_size, 9);
    base.color = [...preset.color];
  }

  if (base.attack_family === "in_page_white_text") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    const preset = RENDERING_REGIME_PRESETS.white_text;
    base.rendering_regime = "white_text";
    base.render_mode = preset.render_mode;
    base.font_size = Math.max(base.font_size, 9);
    base.color = [...preset.color];
  }

  if (base.attack_family === "in_page_tiny_text") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    const preset = RENDERING_REGIME_PRESETS.tiny_font;
    base.rendering_regime = "tiny_font";
    base.render_mode = preset.render_mode;
    base.font_size = Math.min(base.font_size, preset.font_size);
    base.color = [...preset.color];
  }

  if (base.attack_family === "in_page_split_text_objects") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    const preset = RENDERING_REGIME_PRESETS.invisible_render_mode;
    base.rendering_regime = "invisible_render_mode";
    base.render_mode = preset.render_mode;
    base.font_size = Math.max(base.font_size, 9);
    base.color = [...preset.color];
  }

  if (base.attack_family === "layout_mimicry") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    const preset = RENDERING_REGIME_PRESETS.white_text;
    base.rendering_regime = "white_text";
    base.render_mode = preset.render_mode;
    base.font_size = Math.max(base.font_size, 7);
    base.color = [...preset.color];
    base.artifact_wrapper = false;
    base.artifact_regime = "no_artifact";
  }

  if (base.attack_family === "semantic_fragmentation") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    const preset = RENDERING_REGIME_PRESETS.invisible_render_mode;
    base.rendering_regime = "invisible_render_mode";
    base.render_mode = preset.render_mode;
    base.font_size = Math.max(base.font_size, 9);
    base.color = [...preset.color];
    base.artifact_wrapper = false;
    base.artifact_regime = "no_artifact";
  }

  if (base.attack_family === "existing_stream_patch") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    const preset = RENDERING_REGIME_PRESETS.invisible_render_mode;
    base.rendering_regime = "invisible_render_mode";
    base.structural_regime = "inject_into_existing_stream";
    base.render_mode = preset.render_mode;
    base.font_size = Math.max(base.font_size, 9);
    base.color = [...preset.color];
    base.artifact_wrapper = false;
    base.artifact_regime = "no_artifact";
  }

  if (base.attack_family === "in_page_low_contrast_text") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.inside_page];
    }
    base.rendering_regime = "white_text";
    base.render_mode = 0;
    base.font_size = Math.max(base.font_size, 9);
    base.color = [0.96, 0.96, 0.96];
    base.artifact_wrapper = false;
    base.artifact_regime = "no_artifact";
  }

  if (base.attack_family === "margin_microtext") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "near_margin";
      base.coordinates = [...SPATIAL_REGIME_COORDINATES.near_margin];
    }
    const preset = RENDERING_REGIME_PRESETS.tiny_font;
    base.rendering_regime = "tiny_font";
    base.render_mode = preset.render_mode;
    base.font_size = Math.min(base.font_size, 1.2);
    base.color = [...preset.color];
    base.artifact_wrapper = false;
    base.artifact_regime = "no_artifact";
  }

  if (base.attack_family === "steganographic_acrostic") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [0.12, 0.78];
    }
    base.rendering_regime = "normal_visible";
    base.render_mode = 0;
    // Body-text size; at 12pt the strong acrostic cannot fit on one page.
    base.font_size = 8;
    base.color = [0, 0, 0];
    base.artifact_wrapper = false;
    base.artifact_regime = "no_artifact";
  }

  if (base.attack_family === "microglyph_steganography") {
    if (base.coordinates_mode === "regime") {
      base.spatial_regime = "inside_page";
      base.coordinates = [0.5, 0.5];
    }
    base.rendering_regime = "tiny_font";
    base.render_mode = 0;
    base.font_size = Math.min(base.font_size, 0.8);
    base.color = [0, 0, 0];
    base.artifact_wrapper = false;
    base.artifact_regime = "no_artifact";
  }

  return base;
}

export function assertResolvedInjectionConfig(
  config: InjectionConfig
): InjectionConfig {
  if (!VALID_SPATIAL_REGIMES.has(config.spatial_regime)) {
    throw new Error(`Invalid resolved spatial_regime: ${String(config.spatial_regime)}`);
  }

  if (!VALID_RENDERING_REGIMES.has(config.rendering_regime)) {
    throw new Error(
      `Invalid resolved rendering_regime: ${String(config.rendering_regime)}`
    );
  }

  if (!VALID_STRUCTURAL_REGIMES.has(config.structural_regime)) {
    throw new Error(
      `Invalid resolved structural_regime: ${String(config.structural_regime)}`
    );
  }

  if (!VALID_ARTIFACT_REGIMES.has(config.artifact_regime)) {
    throw new Error(
      `Invalid resolved artifact_regime: ${String(config.artifact_regime)}`
    );
  }

  if (!VALID_ATTACK_FAMILIES.has(config.attack_family)) {
    throw new Error(
      `Invalid resolved attack_family: ${String(config.attack_family)}`
    );
  }

  if (!VALID_ATTACK_STRENGTHS.has(config.attack_strength)) {
    throw new Error(
      `Invalid resolved attack_strength: ${String(config.attack_strength)}`
    );
  }

  if (!VALID_COORDINATES_MODES.has(config.coordinates_mode)) {
    throw new Error(
      `Invalid resolved coordinates_mode: ${String(config.coordinates_mode)}`
    );
  }

  if (!Array.isArray(config.coordinates) || config.coordinates.length !== 2) {
    throw new Error("Invalid resolved coordinates: expected a length-2 array.");
  }
  const [x, y] = config.coordinates;
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    throw new Error("Invalid resolved coordinates: expected finite [x, y].");
  }

  if (!Number.isFinite(config.font_size) || config.font_size <= 0) {
    throw new Error("Invalid resolved font_size: expected finite number > 0.");
  }

  if (
    !Number.isInteger(config.render_mode) ||
    config.render_mode < 0 ||
    config.render_mode > 7
  ) {
    throw new Error("Invalid resolved render_mode: expected integer in [0, 7].");
  }

  if (
    !Array.isArray(config.color) ||
    config.color.length !== 3 ||
    config.color.some((channel) => !Number.isFinite(channel) || channel < 0 || channel > 1)
  ) {
    throw new Error("Invalid resolved color: expected [r,g,b] with channels in [0,1].");
  }

  if (config.artifact_wrapper !== (config.artifact_regime === "artifact_wrapped")) {
    throw new Error(
      "Invalid resolved artifact fields: artifact_wrapper and artifact_regime are inconsistent."
    );
  }

  if (
    config.attack_family !== "near_margin_normal_font" &&
    config.attack_family !== "layout_mimicry" &&
    config.attack_family !== "semantic_fragmentation" &&
    config.attack_family !== "existing_stream_patch" &&
    config.attack_family !== "in_page_low_contrast_text" &&
    config.attack_family !== "steganographic_acrostic" &&
    (config.spatial_regime === "inside_page" ||
      config.spatial_regime === "near_margin") &&
    config.rendering_regime === "normal_visible"
  ) {
    throw new Error(
      "Invalid resolved compatibility: on-page + normal_visible must not survive resolution."
    );
  }

  if (
    !Array.isArray(config.compatibility_notes) ||
    config.compatibility_notes.some((note) => typeof note !== "string")
  ) {
    throw new Error("Invalid resolved compatibility_notes: expected string array.");
  }

  return config;
}
