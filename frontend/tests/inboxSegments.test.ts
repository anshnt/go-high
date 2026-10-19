import assert from "node:assert/strict";
import { test } from "node:test";
import { charsLeft, costLabel, segmentLabel, smsSegments } from "../src/inbox/segments.ts";

test("plain text is GSM-7: one segment up to 160 characters, then 153 per segment", () => {
  assert.deepEqual(smsSegments(""), { encoding: "gsm7", segments: 0, chars: 0 });
  assert.deepEqual(smsSegments("Hi Ada, your invoice is ready."), { encoding: "gsm7", segments: 1, chars: 30 });
  assert.equal(smsSegments("a".repeat(160)).segments, 1);
  assert.equal(smsSegments("a".repeat(161)).segments, 2);
  assert.equal(smsSegments("a".repeat(306)).segments, 2);
  assert.equal(smsSegments("a".repeat(307)).segments, 3);
});

test("the extension table costs two characters, so a euro sign near the limit can start a new segment", () => {
  assert.deepEqual(smsSegments("Total: €40"), { encoding: "gsm7", segments: 1, chars: 11 });
  assert.equal(smsSegments("a".repeat(159) + "€").segments, 2); // 159 + 2 > 160
  assert.equal(smsSegments("{x}").chars, 5);
});

test("one character outside GSM-7 makes the whole message Unicode: 70, then 67 per segment, an emoji is two units", () => {
  const u = smsSegments("Café ✓");
  assert.equal(u.encoding, "ucs2");
  assert.equal(u.segments, 1);
  assert.equal(smsSegments("✓".repeat(70)).segments, 1);
  assert.equal(smsSegments("✓".repeat(71)).segments, 2);
  assert.deepEqual(smsSegments("\u{1F600}".repeat(35)), { encoding: "ucs2", segments: 1, chars: 70 });
  assert.equal(smsSegments("\u{1F600}".repeat(36)).segments, 2);
  // a two-unit character is never split across segments: 134 units would be two segments of 67, but the emoji cannot straddle them
  assert.equal(smsSegments("✓".repeat(66) + "\u{1F600}" + "✓".repeat(66)).segments, 3);
});

test("the words under the box say segments, characters, Unicode and the price when the channel has one", () => {
  assert.equal(segmentLabel({ encoding: "gsm7", segments: 1, chars: 30, estimated_cost: "0.000000" }), "1 segment · 30 characters");
  assert.equal(segmentLabel({ encoding: "gsm7", segments: 2, chars: 200, estimated_cost: "0.015800" }), "2 segments · 200 characters · about $0.0158");
  assert.equal(segmentLabel({ encoding: "ucs2", segments: 3, chars: 150, estimated_cost: "0.024" }), "3 segments · 150 characters · Unicode, shorter segments · about $0.024");
  assert.equal(segmentLabel({ encoding: "gsm7", segments: 1, chars: 1 }), "1 segment · 1 character");
  assert.equal(segmentLabel({ encoding: "gsm7", segments: 0, chars: 0 }), "");
});

test("a price shows enough digits to mean something and no trailing zeros", () => {
  assert.equal(costLabel("0.0079"), "$0.0079");
  assert.equal(costLabel("0.016000"), "$0.016");
  assert.equal(costLabel("0.5"), "$0.5");
  assert.equal(costLabel("2.00"), "$2");
  assert.equal(costLabel("12.3456"), "$12.35");
  assert.equal(costLabel("0"), "");
  assert.equal(costLabel(null), "");
  assert.equal(costLabel("abc"), "");
});

test("characters left in the segment you are in", () => {
  assert.equal(charsLeft(smsSegments("")), 160);
  assert.equal(charsLeft(smsSegments("a".repeat(150))), 10);
  assert.equal(charsLeft(smsSegments("a".repeat(200))), 106); // 2 x 153 - 200
  assert.equal(charsLeft(smsSegments("✓".repeat(10))), 60);
});
