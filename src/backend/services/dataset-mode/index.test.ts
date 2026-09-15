import assert from "node:assert/strict";
import test from "node:test";

process.env.TURSO_CONNECTION_URL =
  process.env.TURSO_CONNECTION_URL || "file::memory:?cache=shared";
process.env.TURSO_AUTH_TOKEN = process.env.TURSO_AUTH_TOKEN || "test-token";

const DATASET_MODULE_PATH = "./index";

type DatasetModeModule = typeof import("./index");
let datasetModulePromise: Promise<DatasetModeModule> | null = null;

async function loadDatasetModule(): Promise<DatasetModeModule> {
  if (!datasetModulePromise) {
    datasetModulePromise = import(DATASET_MODULE_PATH);
  }
  return datasetModulePromise;
}

function createSourceFixtures(count: number): any[] {
  return Array.from({ length: count }, (_, idx) => {
    const id = idx + 1;
    const isEven = id % 2 === 0;
    return {
      id,
      originalFilename: `doc-${id}.pdf`,
      filePath: `storage/uploads/doc-${id}.pdf`,
      fileType: "application/pdf",
      metadata: {},
      sourceUploadPath: `uploads/doc-${id}.pdf`,
      benignRegistry: {
        stratum_key: isEven ? "stratum-even" : "stratum-odd",
      },
    };
  });
}

function comboKey(combo: {
  spatial_regime: string;
  rendering_regime: string;
  structural_regime: string;
  artifact_wrapper: boolean;
  message_type: string;
  attack_family: string;
  attack_strength: string;
}): string {
  return [
    combo.spatial_regime,
    combo.rendering_regime,
    combo.structural_regime,
    String(combo.artifact_wrapper),
    combo.message_type,
    combo.attack_family,
    combo.attack_strength,
  ].join("|");
}

test("regime compatibility filtering excludes on-page + normal_visible", async () => {
  const mod = await loadDatasetModule();

  const combinations = mod.buildRegimeCombinations({
    spatial: [
      "extreme_off_page",
      "negative_off_page",
      "near_margin",
      "inside_page",
    ],
    rendering: [
      "invisible_render_mode",
      "tiny_font",
      "white_text",
      "normal_visible",
    ],
    structural: ["append_new_stream", "prepend_stream", "inject_into_existing_stream"],
    artifactWrapper: [true, false],
    messageType: ["instruction_override", "task_hijack", "policy_framing"],
    attackFamily: ["plain_single_block"],
    attackStrength: ["medium"],
  });

  assert.equal(combinations.length, 252);
  assert.ok(
    combinations.every(
      (combo) =>
        !(
          (combo.spatial_regime === "inside_page" ||
            combo.spatial_regime === "near_margin") &&
          combo.rendering_regime === "normal_visible"
        )
    )
  );
});

test("archetype orthogonality holds across compatible regime combinations", async () => {
  const mod = await loadDatasetModule();

  const combinations = mod.buildRegimeCombinations({
    spatial: [
      "extreme_off_page",
      "negative_off_page",
      "near_margin",
      "inside_page",
    ],
    rendering: [
      "invisible_render_mode",
      "tiny_font",
      "white_text",
      "normal_visible",
    ],
    structural: ["append_new_stream", "prepend_stream", "inject_into_existing_stream"],
    artifactWrapper: [true, false],
    messageType: ["instruction_override", "task_hijack", "policy_framing"],
    attackFamily: ["plain_single_block"],
    attackStrength: ["medium"],
  });

  const byMessageType = new Map<string, typeof combinations>();
  for (const combo of combinations) {
    const bucket = byMessageType.get(combo.message_type) || [];
    bucket.push(combo);
    byMessageType.set(combo.message_type, bucket);
  }

  assert.equal(byMessageType.size, 3);
  assert.deepEqual(
    Array.from(byMessageType.values()).map((items) => items.length),
    [84, 84, 84]
  );

  for (const [messageType, messageCombos] of byMessageType.entries()) {
    const spatial = new Set(messageCombos.map((entry) => entry.spatial_regime));
    const rendering = new Set(messageCombos.map((entry) => entry.rendering_regime));
    const structural = new Set(messageCombos.map((entry) => entry.structural_regime));
    const artifact = new Set(messageCombos.map((entry) => entry.artifact_wrapper));

    assert.deepEqual(
      Array.from(spatial).sort(),
      ["extreme_off_page", "inside_page", "near_margin", "negative_off_page"]
    );
    assert.deepEqual(
      Array.from(rendering).sort(),
      ["invisible_render_mode", "normal_visible", "tiny_font", "white_text"]
    );
    assert.deepEqual(
      Array.from(structural).sort(),
      ["append_new_stream", "inject_into_existing_stream", "prepend_stream"]
    );
    assert.deepEqual(Array.from(artifact).sort(), [false, true]);

    const hasOnPageNormalVisible = messageCombos.some(
      (combo) =>
        (combo.spatial_regime === "inside_page" ||
          combo.spatial_regime === "near_margin") &&
        combo.rendering_regime === "normal_visible"
    );
    assert.equal(
      hasOnPageNormalVisible,
      false,
      `unexpected incompatible combo for ${messageType}`
    );
  }
});

test("processing concurrency normalization is bounded and env-aware", async () => {
  const mod = await loadDatasetModule();
  const original = process.env.DATASET_MODE_PROCESSING_CONCURRENCY;

  try {
    delete process.env.DATASET_MODE_PROCESSING_CONCURRENCY;
    assert.equal(mod.normalizeProcessingConcurrency(0), 1);
    assert.equal(mod.normalizeProcessingConcurrency(99), 64);

    process.env.DATASET_MODE_PROCESSING_CONCURRENCY = "6";
    assert.equal(mod.normalizeProcessingConcurrency(undefined), 6);

    process.env.DATASET_MODE_PROCESSING_CONCURRENCY = "garbage";
    const fallback = mod.normalizeProcessingConcurrency(undefined);
    assert.ok(fallback >= 1);
    assert.ok(fallback <= 8);
  } finally {
    if (original === undefined) {
      delete process.env.DATASET_MODE_PROCESSING_CONCURRENCY;
    } else {
      process.env.DATASET_MODE_PROCESSING_CONCURRENCY = original;
    }
  }
});

test("matched benign confounder mapping covers every attack family", async () => {
  const mod = await loadDatasetModule();

  const expected = {
    plain_single_block: "benign_in_page_invisible_note",
    split_text_objects: "benign_in_page_split_layout",
    header_footer_like: "benign_in_page_tiny_footer",
    near_margin_normal_font: "benign_margin_microtext",
    in_page_invisible_text: "benign_in_page_invisible_note",
    in_page_white_text: "benign_in_page_white_watermark",
    in_page_tiny_text: "benign_in_page_tiny_footer",
    in_page_split_text_objects: "benign_in_page_split_layout",
    layout_mimicry: "benign_layout_mimicry_note",
    semantic_fragmentation: "benign_semantic_fragmentation_note",
    existing_stream_patch: "benign_existing_stream_note",
    in_page_low_contrast_text: "benign_low_contrast_watermark",
    margin_microtext: "benign_margin_microtext",
    steganographic_acrostic: "benign_acrostic_editorial_note",
    microglyph_steganography: "benign_microglyph_registration_mark",
  } as const;

  for (const [attackFamily, confounderFamily] of Object.entries(expected)) {
    assert.equal(
      mod.selectMatchedBenignConfounderFamily(attackFamily as any),
      confounderFamily,
      `bad matched confounder for ${attackFamily}`
    );
  }
});

test("matched benign confounder injection config preserves target physical regime", async () => {
  const mod = await loadDatasetModule();

  const target = {
    attack_family: "margin_microtext",
    attack_strength: "strong",
    spatial_regime: "near_margin",
    rendering_regime: "tiny_font",
    structural_regime: "inject_into_existing_stream",
    artifact_wrapper: false,
    artifact_regime: "no_artifact",
    font_size: 0.8,
    coordinates: [10, 0.5],
    coordinates_mode: "regime",
    render_mode: 0,
    color: [0, 0, 0],
    compatibility_notes: [],
  };

  assert.deepEqual(
    mod.buildBenignConfounderInjectionConfig(
      "benign_margin_microtext",
      target as any
    ),
    target
  );
});

test("injected and confounder configs keep regime anchors through the ADA bridge", async () => {
  const mod = await loadDatasetModule();
  const { resolveInjectionConfig } = await import(
    "../processing/layers/02-watermarking/injection-config"
  );

  const target = resolveInjectionConfig({
    attack_family: "steganographic_acrostic",
    attack_strength: "weak",
    spatial_regime: "inside_page",
    rendering_regime: "normal_visible",
    structural_regime: "append_new_stream",
    artifact_wrapper: false,
  });
  const confounder = mod.buildBenignConfounderInjectionConfig(
    mod.selectMatchedBenignConfounderFamily("steganographic_acrostic"),
    target
  );

  // processAdaPolicyLayer resolves its input again before calling Python.
  const bridgedTarget = resolveInjectionConfig(target);
  const bridgedConfounder = resolveInjectionConfig(confounder);
  assert.equal(bridgedTarget.coordinates_mode, "regime");
  assert.deepEqual(bridgedTarget.coordinates, [0.12, 0.78]);
  assert.deepEqual(bridgedConfounder, bridgedTarget);
});

test("dataset balancing is quota-based and reproducible with seeds", async () => {
  const mod = await loadDatasetModule();
  const sources = createSourceFixtures(8);
  const combinations = mod.buildRegimeCombinations({
    spatial: ["extreme_off_page", "near_margin"],
    rendering: ["invisible_render_mode", "tiny_font"],
    structural: ["append_new_stream"],
    artifactWrapper: [true, false],
    messageType: ["instruction_override", "task_hijack"],
    attackFamily: ["plain_single_block"],
    attackStrength: ["medium"],
  });

  const targetSamples = 120;

  const assignmentsRunA = mod.buildQuotaBalancedAssignments(
    sources as any,
    combinations,
    targetSamples,
    mod.createSeededRng(2026)
  );
  const assignmentsRunB = mod.buildQuotaBalancedAssignments(
    sources as any,
    combinations,
    targetSamples,
    mod.createSeededRng(2026)
  );
  const assignmentsRunC = mod.buildQuotaBalancedAssignments(
    sources as any,
    combinations,
    targetSamples,
    mod.createSeededRng(2027)
  );

  assert.equal(assignmentsRunA.length, targetSamples);
  assert.deepEqual(assignmentsRunA, assignmentsRunB);
  assert.notDeepEqual(assignmentsRunA, assignmentsRunC);

  const comboCounts = new Map<string, number>();
  for (const assignment of assignmentsRunA) {
    const key = comboKey(assignment.combo);
    comboCounts.set(key, (comboCounts.get(key) || 0) + 1);
  }
  const perComboCounts = Array.from(comboCounts.values());
  const minCount = Math.min(...perComboCounts);
  const maxCount = Math.max(...perComboCounts);
  assert.ok(maxCount - minCount <= 1);

  const occurrencesBySource = new Map<number, number[]>();
  for (const assignment of assignmentsRunA) {
    const list = occurrencesBySource.get(assignment.source.id) || [];
    list.push(assignment.source_occurrence_index);
    occurrencesBySource.set(assignment.source.id, list);
  }

  for (const occurrenceList of occurrencesBySource.values()) {
    const sorted = [...occurrenceList].sort((a, b) => a - b);
    for (let idx = 0; idx < sorted.length; idx++) {
      assert.equal(sorted[idx], idx + 1);
    }
  }
});

function buildPolicyWithWordCount(words: number): string {
  const tokens = Array.from({ length: words }, (_, idx) => `token_${idx}`);
  return [
    "<SYSTEM_POLICY_DO_NOT_REMOVE>",
    tokens.join(" "),
    "</SYSTEM_POLICY_DO_NOT_REMOVE>",
  ].join("\n");
}

test("archetype length band validation enforces triad constraints", async () => {
  const mod = await loadDatasetModule();

  const validSet = {
    instruction_override: buildPolicyWithWordCount(150),
    task_hijack: buildPolicyWithWordCount(20),
    policy_framing: buildPolicyWithWordCount(80),
    system_extraction: buildPolicyWithWordCount(70),
    refusal_suppression: buildPolicyWithWordCount(70),
    data_exfiltration: buildPolicyWithWordCount(70),
    agent_tool_manipulation: buildPolicyWithWordCount(150),
    summarization_steering: buildPolicyWithWordCount(70),
  };
  assert.doesNotThrow(() => mod.validateArchetypePolicyTextSet(validSet));

  const invalidShortBand = {
    ...validSet,
    task_hijack: buildPolicyWithWordCount(80),
  };
  assert.throws(() => mod.validateArchetypePolicyTextSet(invalidShortBand));

  const invalidEnvelope = {
    ...validSet,
    policy_framing: "<SYSTEM_POLICY_DO_NOT_REMOVE>\nmissing closing tag",
  };
  assert.throws(() => mod.validateArchetypePolicyTextSet(invalidEnvelope));
});

function buildInjectedValidationResult(overrides: Record<string, unknown> = {}) {
  return {
    success: true,
    harness_version: "phase5-v2",
    pdf_path: "sample.pdf",
    expected_marker: "[DATASET_SAMPLE_ID=sample_0001][MESSAGE_TYPE=instruction_override]",
    expected_raw_extraction: true,
    raw_extraction_check: {
      passed: true,
      found_marker: true,
      expected_found_marker: true,
      matched_marker_count: 1,
      snippet: "marker",
    },
    extractor_matrix_check: {
      passed: true,
      reason: "marker_detected_by_matrix",
      expected_found_marker: true,
      min_extractors_required: 2,
      available_extractors: 3,
      ran_extractors: 3,
      positive_extractors: 2,
      negative_extractors: 1,
      found_by: ["pypdf_text", "pdfplumber_text"],
      missed_by: ["raw_stream"],
      extractors: [],
    },
    render_visibility_check: {
      passed: true,
      reason: "renderer_and_operator_checks_passed",
      mode: "renderer+operator_inference",
      marker_instances: 1,
      inferred_hidden_instances: 1,
      inferred_visible_instances: 0,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
    parse_errors: 0,
    ...overrides,
  };
}

test("split_text_objects accepts extractor-positive fragmented marker evidence", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    raw_extraction_check: {
      passed: false,
      found_marker: false,
      expected_found_marker: true,
      matched_marker_count: 0,
      snippet: null,
    },
    render_visibility_check: {
      passed: false,
      reason: "marker_text_not_detected_in_parsed_operations",
      mode: "renderer+operator_inference",
      marker_instances: 0,
      inferred_hidden_instances: 0,
      inferred_visible_instances: 0,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
  });

  assert.deepEqual(
    mod.evaluateInjectedValidationForAttackFamily(
      "split_text_objects",
      injected as any
    ),
    {
      rawPresencePassed: false,
      presenceRequirementPassed: true,
      extractorMatrixPassed: true,
      renderStealthPassed: true,
    }
  );
});

test("near_margin_normal_font accepts renderer-nonvisible subtle placements", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    render_visibility_check: {
      passed: false,
      reason: "marker_instances_may_be_visible",
      mode: "renderer+operator_inference",
      marker_instances: 1,
      inferred_hidden_instances: 0,
      inferred_visible_instances: 1,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
  });

  assert.deepEqual(
    mod.evaluateInjectedValidationForAttackFamily(
      "near_margin_normal_font",
      injected as any
    ),
    {
      rawPresencePassed: true,
      presenceRequirementPassed: true,
      extractorMatrixPassed: true,
      renderStealthPassed: true,
    }
  );
});

test("subtle families require a real renderer verdict", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    render_visibility_check: {
      passed: true,
      reason: "renderer_skipped",
      mode: "operator_inference_only",
      marker_instances: 1,
      inferred_hidden_instances: 1,
      inferred_visible_instances: 0,
      evidence: [],
      renderer_evidence: {
        ran: false,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 0,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: "renderer skipped",
      },
    },
  });

  assert.deepEqual(
    mod.evaluateInjectedValidationForAttackFamily(
      "near_margin_normal_font",
      injected as any
    ),
    {
      rawPresencePassed: true,
      presenceRequirementPassed: true,
      extractorMatrixPassed: true,
      renderStealthPassed: false,
    }
  );
});

test("hard in-page families require renderer-nonvisible evidence", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    render_visibility_check: {
      passed: false,
      reason: "marker_instances_may_be_visible",
      mode: "renderer+operator_inference",
      marker_instances: 1,
      inferred_hidden_instances: 0,
      inferred_visible_instances: 1,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
  });

  for (const attackFamily of [
    "in_page_invisible_text",
    "in_page_white_text",
    "in_page_tiny_text",
    "layout_mimicry",
    "existing_stream_patch",
    "in_page_low_contrast_text",
    "margin_microtext",
    "steganographic_acrostic",
  ] as const) {
    assert.deepEqual(
      mod.evaluateInjectedValidationForAttackFamily(
        attackFamily,
        injected as any
      ),
      {
        rawPresencePassed: true,
        presenceRequirementPassed: true,
        extractorMatrixPassed: true,
        renderStealthPassed: true,
      }
    );
  }
});

test("microglyph_steganography accepts fragmented extractor evidence", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    raw_extraction_check: {
      passed: false,
      found_marker: false,
      expected_found_marker: true,
      matched_marker_count: 0,
      snippet: null,
    },
    render_visibility_check: {
      passed: false,
      reason: "marker_text_fragmented_into_microglyphs",
      mode: "renderer+operator_inference",
      marker_instances: 0,
      inferred_hidden_instances: 0,
      inferred_visible_instances: 0,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
  });

  assert.deepEqual(
    mod.evaluateInjectedValidationForAttackFamily(
      "microglyph_steganography",
      injected as any
    ),
    {
      rawPresencePassed: false,
      presenceRequirementPassed: true,
      extractorMatrixPassed: true,
      renderStealthPassed: true,
    }
  );
});

test("steganographic_acrostic survives compatibility filtering for visible text", async () => {
  const mod = await loadDatasetModule();

  const combinations = mod.buildRegimeCombinations({
    spatial: ["inside_page"],
    rendering: ["normal_visible"],
    structural: ["inject_into_existing_stream"],
    artifactWrapper: [false],
    messageType: ["instruction_override"],
    attackFamily: ["steganographic_acrostic"],
    attackStrength: ["medium"],
  });

  assert.equal(combinations.length, 1);
  assert.equal(combinations[0].attack_family, "steganographic_acrostic");
});

test("semantic_fragmentation accepts fragmented extractor evidence", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    raw_extraction_check: {
      passed: false,
      found_marker: false,
      expected_found_marker: true,
      matched_marker_count: 0,
      snippet: null,
    },
    render_visibility_check: {
      passed: false,
      reason: "marker_text_not_detected_in_parsed_operations",
      mode: "renderer+operator_inference",
      marker_instances: 0,
      inferred_hidden_instances: 0,
      inferred_visible_instances: 0,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
  });

  assert.deepEqual(
    mod.evaluateInjectedValidationForAttackFamily(
      "semantic_fragmentation",
      injected as any
    ),
    {
      rawPresencePassed: false,
      presenceRequirementPassed: true,
      extractorMatrixPassed: true,
      renderStealthPassed: true,
    }
  );
});

test("in_page_split_text_objects accepts fragmented extractor evidence", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    raw_extraction_check: {
      passed: false,
      found_marker: false,
      expected_found_marker: true,
      matched_marker_count: 0,
      snippet: null,
    },
    render_visibility_check: {
      passed: false,
      reason: "marker_text_not_detected_in_parsed_operations",
      mode: "renderer+operator_inference",
      marker_instances: 0,
      inferred_hidden_instances: 0,
      inferred_visible_instances: 0,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
  });

  assert.deepEqual(
    mod.evaluateInjectedValidationForAttackFamily(
      "in_page_split_text_objects",
      injected as any
    ),
    {
      rawPresencePassed: false,
      presenceRequirementPassed: true,
      extractorMatrixPassed: true,
      renderStealthPassed: true,
    }
  );
});

test("plain_single_block keeps strict legacy hidden-text requirements", async () => {
  const mod = await loadDatasetModule();

  const injected = buildInjectedValidationResult({
    render_visibility_check: {
      passed: false,
      reason: "marker_instances_may_be_visible",
      mode: "renderer+operator_inference",
      marker_instances: 1,
      inferred_hidden_instances: 0,
      inferred_visible_instances: 1,
      evidence: [],
      renderer_evidence: {
        ran: true,
        engine: "pymupdf+pytesseract",
        dpi: 200,
        pages_scanned: 1,
        marker_visible: false,
        visible_pages: [],
        marker_tokens: ["dataset_sample_id", "sample_0001"],
        token_threshold: 2,
        page_evidence: [],
        error: null,
      },
    },
  });

  assert.deepEqual(
    mod.evaluateInjectedValidationForAttackFamily(
      "plain_single_block",
      injected as any
    ),
    {
      rawPresencePassed: true,
      presenceRequirementPassed: true,
      extractorMatrixPassed: true,
      renderStealthPassed: false,
    }
  );
});
