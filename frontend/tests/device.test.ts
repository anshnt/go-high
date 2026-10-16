import assert from "node:assert/strict";
import { test } from "node:test";
import { describeDevice, timeAgo, waitText } from "../src/lib/device.ts";

const UA = {
  chromeWin: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  edgeWin: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
  firefoxLinux: "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
  safariMac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
  safariIphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  chromeAndroid: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
  chromeIphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.0.0 Mobile/15E148 Safari/604.1",
  headless: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/126.0.0.0 Safari/537.36",
};

test("browser and system in plain words", () => {
  assert.equal(describeDevice(UA.chromeWin), "Chrome on Windows");
  assert.equal(describeDevice(UA.edgeWin), "Edge on Windows");
  assert.equal(describeDevice(UA.firefoxLinux), "Firefox on Linux");
  assert.equal(describeDevice(UA.safariMac), "Safari on macOS");
  assert.equal(describeDevice(UA.safariIphone), "Safari on iPhone");
  assert.equal(describeDevice(UA.chromeAndroid), "Chrome on Android");
  assert.equal(describeDevice(UA.chromeIphone), "Chrome on iPhone");
  assert.equal(describeDevice(UA.headless), "Chrome on Windows");
});

test("empty, missing and non-browser agents", () => {
  assert.equal(describeDevice(null), "Unknown device");
  assert.equal(describeDevice(undefined), "Unknown device");
  assert.equal(describeDevice("  "), "Unknown device");
  assert.equal(describeDevice("curl/8.4.0"), "Command line or script");
  assert.equal(describeDevice("Mozilla/5.0 (compatible; Something)"), "Unknown device");
  assert.equal(describeDevice("Mozilla/5.0 (X11; Linux x86_64)"), "Browser on Linux");
});

test("relative time", () => {
  const now = Date.parse("2026-10-16T12:00:00Z");
  const ago = (s: number) => timeAgo(new Date(now - s * 1000).toISOString(), now);
  assert.equal(ago(5), "Just now");
  assert.equal(ago(59), "Just now");
  assert.equal(ago(60), "1 minute ago");
  assert.equal(ago(5 * 60), "5 minutes ago");
  assert.equal(ago(3 * 3600), "3 hours ago");
  assert.equal(ago(86_400), "yesterday");
  assert.equal(ago(3 * 86_400), "3 days ago");
  assert.equal(ago(-30), "Just now"); // clock skew: a timestamp slightly in the future
  assert.match(ago(60 * 86_400), /2026/);
  assert.equal(timeAgo("not a date", now), "Unknown");
});

test("retry wait text", () => {
  assert.equal(waitText(1), "1 second");
  assert.equal(waitText(45), "45 seconds");
  assert.equal(waitText(900), "15 minutes");
  assert.equal(waitText(61), "2 minutes");
  assert.equal(waitText(3600), "1 hour");
});
