import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, test } from "vitest";
import type { SseEvent } from "../generated";
import schema from "../schema.json" with { type: "json" };

// Ajv's own discriminator implementation can't trace through `allOf`, but
// `oneOf` already enforces single-match dispatch — register the keyword as a
// no-op so strict mode permits its presence (it's there for codegen).
const ajv = addFormats(new Ajv({ allErrors: true, strict: true }));
ajv.addKeyword({ keyword: "discriminator" });
const validate = ajv.compile(schema);

const assertSseEvent = <T extends SseEvent>(value: T): T => value;

const MISSION_ID = "00000000-0000-0000-0000-000000000001";
const TASK_ID = "00000000-0000-0000-0000-000000000002";

describe("SSE event round-trip", () => {
  test("token event validates", () => {
    const event = assertSseEvent({
      type: "token",
      content: "hello",
      mission_id: MISSION_ID,
      task_id: TASK_ID,
      seq: 0,
    });
    expect(validate(event)).toBe(true);
  });

  test("rejects unknown type", () => {
    const bad = {
      type: "fabricated",
      content: "x",
      mission_id: MISSION_ID,
      seq: 0,
    };
    expect(validate(bad)).toBe(false);
  });

  test("rejects missing required mission_id", () => {
    const bad = {
      type: "done",
      content: { mission_status: "succeeded" },
      seq: 0,
    };
    expect(validate(bad)).toBe(false);
  });

  test("rejects task event without task_id", () => {
    const bad = {
      type: "task_start",
      content: { url: "https://example.com/", tier: "http" },
      mission_id: MISSION_ID,
      seq: 0,
    };
    expect(validate(bad)).toBe(false);
  });

  test("done event without task_id is fine", () => {
    const event = assertSseEvent({
      type: "done",
      content: { mission_status: "succeeded", cost_cents: 0 },
      mission_id: MISSION_ID,
      seq: 5,
    });
    expect(validate(event)).toBe(true);
  });

  test("rejects negative seq", () => {
    const bad = {
      type: "token",
      content: "hi",
      mission_id: MISSION_ID,
      task_id: TASK_ID,
      seq: -1,
    };
    expect(validate(bad)).toBe(false);
  });

  test("error event with resume_lost code validates", () => {
    const event = assertSseEvent({
      type: "error",
      content: { code: "resume_lost", message: "buffer evicted" },
      mission_id: MISSION_ID,
      seq: 0,
    });
    expect(validate(event)).toBe(true);
  });
});
