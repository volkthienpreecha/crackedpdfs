import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import {
  assertResolvedInjectionConfig,
  resolveInjectionConfig,
  type InjectionConfig,
} from "./injection-config";
import { getPythonExecutable } from "./python-utils";
import { PDF_ATTACK_FAMILIES, PDF_ATTACK_STRENGTHS } from "@/lib/pdf-benchmark-taxonomy";

const PYTHON_BIN = getPythonExecutable();
const INJECT_POLICY_SCRIPT = path.join(
  process.cwd(),
  "src",
  "backend",
  "services",
  "processing",
  "layers",
  "02-watermarking",
  "volks-pdf-blocker-ada-layer-1",
  "inject_policy.py"
);

const PYTHON_VALIDATOR = `
import importlib.util
import json
import sys

script_path = sys.argv[1]
spec = importlib.util.spec_from_file_location("inject_policy", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

payload = json.loads(sys.stdin.read())
validated = module.validate_resolved_injection_config(payload)
print(json.dumps(validated, sort_keys=True))
`;

function validateWithPython(config: unknown): InjectionConfig {
  const stdout = execFileSync(PYTHON_BIN, ["-c", PYTHON_VALIDATOR, INJECT_POLICY_SCRIPT], {
    input: JSON.stringify(config),
    encoding: "utf-8",
    maxBuffer: 10 * 1024 * 1024,
    stdio: ["pipe", "pipe", "ignore"],
  });
  return JSON.parse(stdout) as InjectionConfig;
}

test("TS resolved injection config satisfies Python validator contract", () => {
  const scenarios: unknown[] = [
    {},
    {
      spatial_regime: "near_margin",
      rendering_regime: "tiny_font",
      structural_regime: "prepend_stream",
      artifact_wrapper: false,
    },
    {
      coordinates: [321.25, 432.5],
      font_size: 0.75,
      render_mode: 3,
      color: [0.1, 0.2, 0.3],
    },
    {
      attack_family: "split_text_objects",
      attack_strength: "strong",
      rendering_regime: "tiny_font",
      structural_regime: "inject_into_existing_stream",
    },
    {
      spatial_regime: "inside_page",
      rendering_regime: "normal_visible",
    },
    {
      spatial_regime: "near_margin",
      rendering_regime: "normal_visible",
    },
  ];

  for (const scenario of scenarios) {
    const resolved = assertResolvedInjectionConfig(resolveInjectionConfig(scenario));
    const validated = validateWithPython(resolved);
    assert.deepEqual(validated, resolved);
  }
});

test("Python validator rejects contract violations", () => {
  const resolved = assertResolvedInjectionConfig(resolveInjectionConfig({}));
  const invalidRenderMode = {
    ...resolved,
    render_mode: 9,
  };
  const invalidArtifactConsistency = {
    ...resolved,
    artifact_wrapper: true,
    artifact_regime: "no_artifact",
  };
  const invalidAttackFamily = {
    ...resolved,
    attack_family: "not_real",
  };

  assert.throws(() => validateWithPython(invalidRenderMode), /render_mode|Command failed/);
  assert.throws(
    () => validateWithPython(invalidArtifactConsistency),
    /artifact_wrapper and artifact_regime are inconsistent|Command failed/
  );
  assert.throws(
    () => validateWithPython(invalidAttackFamily),
    /attack_family|Command failed/
  );
});

test("near_margin_normal_font resolves to a normal-looking visible regime", () => {
  const resolved = assertResolvedInjectionConfig(
    resolveInjectionConfig({
      attack_family: "near_margin_normal_font",
      rendering_regime: "white_text",
      spatial_regime: "inside_page",
      font_size: 4,
    })
  );

  assert.equal(resolved.attack_family, "near_margin_normal_font");
  assert.equal(resolved.spatial_regime, "near_margin");
  assert.equal(resolved.rendering_regime, "normal_visible");
  assert.equal(resolved.render_mode, 0);
  assert.deepEqual(resolved.color, [0, 0, 0]);
  assert.equal(resolved.font_size >= 9, true);
  assert.deepEqual(validateWithPython(resolved), resolved);
});

test("header_footer_like does not keep normal_visible after resolution", () => {
  const resolved = assertResolvedInjectionConfig(
    resolveInjectionConfig({
      attack_family: "header_footer_like",
      rendering_regime: "normal_visible",
    })
  );

  assert.equal(resolved.attack_family, "header_footer_like");
  assert.notEqual(resolved.rendering_regime, "normal_visible");
  assert.deepEqual(validateWithPython(resolved), resolved);
});

test("hard in-page families resolve away from off-page geometry", () => {
  const scenarios = [
    {
      attack_family: "in_page_invisible_text",
      expected_rendering: "invisible_render_mode",
      expected_render_mode: 3,
    },
    {
      attack_family: "in_page_white_text",
      expected_rendering: "white_text",
      expected_render_mode: 0,
    },
    {
      attack_family: "in_page_tiny_text",
      expected_rendering: "tiny_font",
      expected_render_mode: 0,
    },
    {
      attack_family: "in_page_split_text_objects",
      expected_rendering: "invisible_render_mode",
      expected_render_mode: 3,
    },
    {
      attack_family: "layout_mimicry",
      expected_rendering: "white_text",
      expected_render_mode: 0,
    },
    {
      attack_family: "semantic_fragmentation",
      expected_rendering: "invisible_render_mode",
      expected_render_mode: 3,
    },
    {
      attack_family: "existing_stream_patch",
      expected_rendering: "invisible_render_mode",
      expected_render_mode: 3,
    },
    {
      attack_family: "in_page_low_contrast_text",
      expected_rendering: "white_text",
      expected_render_mode: 0,
    },
    {
      attack_family: "steganographic_acrostic",
      expected_rendering: "normal_visible",
      expected_render_mode: 0,
      expected_coordinates: [0.12, 0.78],
    },
    {
      attack_family: "microglyph_steganography",
      expected_rendering: "tiny_font",
      expected_render_mode: 0,
    },
  ];

  for (const scenario of scenarios) {
    const resolved = assertResolvedInjectionConfig(
      resolveInjectionConfig({
        attack_family: scenario.attack_family,
        spatial_regime: "extreme_off_page",
        rendering_regime: "normal_visible",
      })
    );

    assert.equal(resolved.attack_family, scenario.attack_family);
    assert.equal(resolved.spatial_regime, "inside_page");
    assert.equal(resolved.rendering_regime, scenario.expected_rendering);
    assert.equal(resolved.render_mode, scenario.expected_render_mode);
    assert.deepEqual(
      resolved.coordinates,
      "expected_coordinates" in scenario ? scenario.expected_coordinates : [0.5, 0.5]
    );
    assert.deepEqual(validateWithPython(resolved), resolved);
  }
});

test("margin_microtext resolves to near-margin tiny text", () => {
  const resolved = assertResolvedInjectionConfig(
    resolveInjectionConfig({
      attack_family: "margin_microtext",
      spatial_regime: "extreme_off_page",
      rendering_regime: "normal_visible",
      font_size: 12,
    })
  );

  assert.equal(resolved.attack_family, "margin_microtext");
  assert.equal(resolved.spatial_regime, "near_margin");
  assert.equal(resolved.rendering_regime, "tiny_font");
  assert.equal(resolved.render_mode, 0);
  assert.equal(resolved.font_size <= 1.2, true);
  assert.deepEqual(validateWithPython(resolved), resolved);
});

test("resolution is idempotent across the full 4,320-config regime grid", () => {
  const spatialRegimes = ["extreme_off_page", "negative_off_page", "near_margin", "inside_page"];
  const renderingRegimes = ["invisible_render_mode", "tiny_font", "white_text", "normal_visible"];
  const structuralRegimes = ["append_new_stream", "prepend_stream", "inject_into_existing_stream"];
  let checked = 0;

  for (const attack_family of PDF_ATTACK_FAMILIES) {
    for (const attack_strength of PDF_ATTACK_STRENGTHS) {
      for (const spatial_regime of spatialRegimes) {
        for (const rendering_regime of renderingRegimes) {
          for (const structural_regime of structuralRegimes) {
            for (const artifact_wrapper of [true, false]) {
              const once = resolveInjectionConfig({
                attack_family,
                attack_strength,
                spatial_regime,
                rendering_regime,
                structural_regime,
                artifact_wrapper,
              });
              const twice = resolveInjectionConfig(once);
              assert.deepEqual(twice, once);
              assert.notEqual(twice, once);
              assert.notEqual(twice.coordinates, once.coordinates);
              checked += 1;
            }
          }
        }
      }
    }
  }

  assert.equal(checked, 15 * 3 * 4 * 4 * 3 * 2);
});

test("regime anchors are never promoted to absolute coordinate overrides", () => {
  // Paper v1 regression: the ADA bridge re-resolved configs, so [0.12, 0.78]
  // became absolute points and payloads landed below the page.
  const acrostic = resolveInjectionConfig({ attack_family: "steganographic_acrostic" });
  assert.equal(acrostic.coordinates_mode, "regime");
  assert.deepEqual(acrostic.coordinates, [0.12, 0.78]);

  const partial = resolveInjectionConfig({
    spatial_regime: "inside_page",
    coordinates: [0.5, 0.5],
    coordinates_mode: "regime",
  });
  assert.equal(partial.coordinates_mode, "regime");

  assert.deepEqual(resolveInjectionConfig(resolveInjectionConfig(partial)), partial);
});

test("explicit coordinates still resolve as overrides", () => {
  const resolved = resolveInjectionConfig({ coordinates: [72, 144] });
  assert.equal(resolved.coordinates_mode, "override");
  assert.deepEqual(resolved.coordinates, [72, 144]);
  assert.deepEqual(resolveInjectionConfig(resolved), resolved);
});

test("resolver and Python validator agree on malformed coordinate arrays", () => {
  // A three-element coordinate array must not pass either side's contract, so
  // the resolved fast path cannot smuggle a config that Python then rejects.
  assert.throws(
    () => assertResolvedInjectionConfig({
      ...resolveInjectionConfig({}),
      coordinates: [72, 144, 200] as unknown as [number, number],
    }),
    /length-2/
  );

  // A malformed array on the input side is dropped, not promoted, so the
  // regime default survives and the two validators agree.
  const resolved = resolveInjectionConfig({
    coordinates: [72, 144, 200] as unknown as [number, number],
  });
  assert.equal(resolved.coordinates_mode, "regime");
  assert.equal(resolved.coordinates.length, 2);
  assert.deepEqual(validateWithPython(resolved), resolved);
});

test("layout-constrained families carry labels the injector can honor", () => {
  for (const spatial_regime of ["extreme_off_page", "negative_off_page", "inside_page", "near_margin"]) {
    const headerFooter = assertResolvedInjectionConfig(
      resolveInjectionConfig({ attack_family: "header_footer_like", spatial_regime })
    );
    assert.equal(headerFooter.spatial_regime, "near_margin");
    assert.deepEqual(validateWithPython(headerFooter), headerFooter);
  }

  const acrostic = assertResolvedInjectionConfig(
    resolveInjectionConfig({ attack_family: "steganographic_acrostic", font_size: 14 })
  );
  assert.equal(acrostic.font_size, 8);
});
