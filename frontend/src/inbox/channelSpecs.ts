// What each channel provider needs (README "Inbox and channels", the table of providers), and how a form's values
// become the API's request. Pure: no DOM, no Vite, so node tests it. Secrets are write-only: they are only ever sent.
import type { Channel, ChannelKind } from "./types.ts";

export type Where = "name" | "address" | "config" | "secret";
export type FieldSpec = {
  key: string;
  where: Where;
  label: string;
  type?: "text" | "password" | "number" | "select" | "color";
  required?: boolean;
  placeholder?: string;
  hint?: string;
  options?: { value: string; label: string }[];
  default?: string;
};

export type Spec = {
  id: string;
  kind: ChannelKind;
  provider: Channel["provider"];
  title: string;
  blurb: string;
  fields: FieldSpec[];
  /** Whether the provider calls us, so there is a webhook URL to paste into its console. */
  hook: boolean;
};

const name = (placeholder: string): FieldSpec => ({ key: "name", where: "name", label: "Name", required: true, placeholder, hint: "Shown in the inbox when you pick what to send on." });

export const SPECS: Spec[] = [
  {
    id: "twilio",
    kind: "sms",
    provider: "twilio",
    title: "SMS with Twilio",
    blurb: "Send and receive text messages on a Twilio number.",
    hook: true,
    fields: [
      name("Main line"),
      { key: "address", where: "address", label: "Sending number", required: true, placeholder: "+14155550123", hint: "In international format. Leave empty if you use a messaging service." },
      { key: "account_sid", where: "config", label: "Account SID", required: true },
      { key: "messaging_service_sid", where: "config", label: "Messaging service SID", hint: "Optional. Use it instead of one number." },
      { key: "auth_token", where: "secret", label: "Auth token", type: "password", required: true },
    ],
  },
  {
    id: "telnyx",
    kind: "sms",
    provider: "telnyx",
    title: "SMS with Telnyx",
    blurb: "Send and receive text messages on a Telnyx number.",
    hook: true,
    fields: [
      name("Telnyx line"),
      { key: "address", where: "address", label: "Sending number", required: true, placeholder: "+14155550123" },
      { key: "public_key", where: "config", label: "Public key", required: true, hint: "Used to check that incoming webhooks come from Telnyx." },
      { key: "messaging_profile_id", where: "config", label: "Messaging profile ID" },
      { key: "api_key", where: "secret", label: "API key", type: "password", required: true },
    ],
  },
  {
    id: "smtp",
    kind: "email",
    provider: "smtp",
    title: "Email with SMTP",
    blurb: "Send mail through any SMTP server. Replies need a mailbox connection or a forwarding address.",
    hook: false,
    fields: [
      name("Support email"),
      { key: "address", where: "address", label: "From address", required: true, placeholder: "hello@example.com" },
      { key: "host", where: "config", label: "SMTP host", required: true, placeholder: "smtp.example.com" },
      { key: "port", where: "config", label: "Port", type: "number", default: "587" },
      { key: "security", where: "config", label: "Security", type: "select", default: "starttls", options: [{ value: "starttls", label: "STARTTLS (port 587)" }, { value: "tls", label: "TLS (port 465)" }] },
      { key: "username", where: "config", label: "Username" },
      { key: "password", where: "secret", label: "Password", type: "password", hint: "Needed when you set a username." },
      { key: "message_id_domain", where: "config", label: "Message-ID domain", hint: "Optional. The domain used in message ids, so replies thread." },
    ],
  },
  {
    id: "mailgun",
    kind: "email",
    provider: "mailgun",
    title: "Email with Mailgun",
    blurb: "Send and receive mail through a Mailgun domain, with delivery reports.",
    hook: true,
    fields: [
      name("Support mail"),
      { key: "address", where: "address", label: "From address", required: true, placeholder: "hello@mg.example.com" },
      { key: "domain", where: "config", label: "Sending domain", required: true, placeholder: "mg.example.com" },
      { key: "region", where: "config", label: "Region", type: "select", default: "us", options: [{ value: "us", label: "United States" }, { value: "eu", label: "Europe" }] },
      { key: "api_key", where: "secret", label: "API key", type: "password", required: true },
      { key: "signing_key", where: "secret", label: "Webhook signing key", type: "password", required: true, hint: "Checks that incoming webhooks come from Mailgun." },
      { key: "message_id_domain", where: "config", label: "Message-ID domain" },
    ],
  },
  {
    id: "meta",
    kind: "whatsapp",
    provider: "meta",
    title: "WhatsApp Business",
    blurb: "Message customers on WhatsApp with the WhatsApp Business platform.",
    hook: true,
    fields: [
      name("WhatsApp"),
      { key: "address", where: "address", label: "Business number", required: true, placeholder: "+14155550123" },
      { key: "phone_number_id", where: "config", label: "Phone number ID", required: true },
      { key: "access_token", where: "secret", label: "Access token", type: "password", required: true },
      { key: "app_secret", where: "secret", label: "App secret", type: "password", required: true },
      { key: "verify_token", where: "secret", label: "Webhook verify token", type: "password", required: true, hint: "Any text you choose. Enter the same one in the provider's console." },
    ],
  },
  {
    id: "internal",
    kind: "webchat",
    provider: "internal",
    title: "Web chat",
    blurb: "A chat bubble for your website. Visitors become contacts when they leave an email or number.",
    hook: false,
    fields: [
      name("Website chat"),
      { key: "title", where: "config", label: "Window title", placeholder: "Chat with us" },
      { key: "greeting", where: "config", label: "Greeting", placeholder: "Hi! How can we help?" },
      { key: "color", where: "config", label: "Colour", type: "color", default: "#4f46e5" },
    ],
  },
];

const PROVIDER_LABEL: Record<Channel["provider"], string> = { twilio: "Twilio", telnyx: "Telnyx", smtp: "SMTP", ses: "SMTP", mailgun: "Mailgun", meta: "WhatsApp Business", internal: "Chat widget" };

/** "Twilio, SMS", "SMTP, email", "WhatsApp Business", "Chat widget": the provider, and the kind only when the provider does not say it. */
export const describeChannel = (ch: Pick<Channel, "provider" | "kind">): string => `${PROVIDER_LABEL[ch.provider]}${ch.kind === "sms" ? " \u00b7 SMS" : ch.kind === "email" ? " \u00b7 Email" : ""}`;

export const specOf = (ch: Pick<Channel, "provider">): Spec => SPECS.find((s) => s.provider === ch.provider) ?? SPECS.find((s) => s.provider === "smtp")!;

/** The sending rules every SMS and WhatsApp channel has, and the reply-to of email. Plain values, so a form can show them as text. */
export type Rules = { segment_cost: string; quiet_start: string; quiet_end: string; cap_max: string; cap_hours: string; reply_to: string };
export const EMPTY_RULES: Rules = { segment_cost: "", quiet_start: "", quiet_end: "", cap_max: "", cap_hours: "", reply_to: "" };
export const hasRules = (kind: ChannelKind) => kind === "sms" || kind === "whatsapp";

export type Values = { fields: Record<string, string>; rules: Rules };

export function emptyValues(spec: Spec): Values {
  return { fields: Object.fromEntries(spec.fields.map((f) => [f.key, f.default ?? ""])), rules: { ...EMPTY_RULES } };
}

const text = (v: unknown) => (v === undefined || v === null ? "" : String(v));

/** The form's values for a channel being edited. Secrets are never sent back by the API, so those fields start empty. */
export function valuesOf(spec: Spec, ch: Channel): Values {
  const config = ch.config ?? {};
  const cap = (config.frequency_cap ?? {}) as { max?: number; hours?: number };
  return {
    fields: Object.fromEntries(spec.fields.map((f) => [f.key, f.where === "name" ? ch.name : f.where === "address" ? (ch.kind === "webchat" ? "" : ch.address) : f.where === "config" ? text(config[f.key] ?? f.default) : ""])),
    rules: { segment_cost: text(config.segment_cost), quiet_start: text(config.quiet_start), quiet_end: text(config.quiet_end), cap_max: text(cap.max), cap_hours: text(cap.hours), reply_to: text(config.reply_to) },
  };
}

type Config = Record<string, unknown>;

/** The settings (`config`) a form's values make. With `clear`, an emptied optional setting is a null, which removes it on a PATCH. */
function configOf(spec: Spec, v: Values, clear: boolean): Config {
  const out: Config = {};
  for (const f of spec.fields) {
    if (f.where !== "config") continue;
    const raw = (v.fields[f.key] ?? "").trim();
    if (raw === "") {
      if (clear) out[f.key] = null;
      continue;
    }
    out[f.key] = f.type === "number" ? Number(raw) : raw;
  }
  if (hasRules(spec.kind)) {
    const r = v.rules;
    const put = (key: string, raw: string, value: unknown = raw) => (raw.trim() === "" ? clear && (out[key] = null) : (out[key] = value));
    if (spec.kind === "sms") put("segment_cost", r.segment_cost, Number(r.segment_cost));
    put("quiet_start", r.quiet_start);
    put("quiet_end", r.quiet_end);
    if (r.cap_max.trim() !== "" || r.cap_hours.trim() !== "") out.frequency_cap = { max: Number(r.cap_max || 0), hours: Number(r.cap_hours || 24) };
    else if (clear) out.frequency_cap = null;
  }
  if (spec.kind === "email") {
    if (v.rules.reply_to.trim()) out.reply_to = v.rules.reply_to.trim();
    else if (clear) out.reply_to = null;
  }
  return out;
}

const secretsOf = (spec: Spec, v: Values): Record<string, string> =>
  Object.fromEntries(spec.fields.filter((f) => f.where === "secret" && (v.fields[f.key] ?? "") !== "").map((f) => [f.key, v.fields[f.key]!]));

const get = (spec: Spec, v: Values, where: Where) => {
  const f = spec.fields.find((x) => x.where === where);
  return f ? (v.fields[f.key] ?? "").trim() : "";
};

/** The POST body that creates a channel. */
export function buildCreate(spec: Spec, v: Values) {
  const secrets = secretsOf(spec, v);
  return { kind: spec.kind, provider: spec.provider, name: get(spec, v, "name"), address: get(spec, v, "address"), config: configOf(spec, v, false), ...(Object.keys(secrets).length ? { secrets } : {}) };
}

/** The PATCH body for an edit: the settings as the form has them (an emptied optional one is removed) and only the secrets that were typed. */
export function buildPatch(spec: Spec, v: Values) {
  const secrets = secretsOf(spec, v);
  const address = get(spec, v, "address");
  return { name: get(spec, v, "name"), ...(spec.kind !== "webchat" ? { address } : {}), config: configOf(spec, v, true), ...(Object.keys(secrets).length ? { secrets } : {}) };
}

/** The server's per-field errors ("config.account_sid", "secrets.auth_token", "address") keyed by the form's field keys. */
export function errorsByField(spec: Spec, fields: Record<string, string> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, message] of Object.entries(fields ?? {})) {
    const key = path.replace(/^(config|secrets)\./, "");
    const match = spec.fields.find((f) => (path === "name" ? f.where === "name" : path === "address" ? f.where === "address" : f.key === key));
    out[match?.key ?? path] = message.charAt(0).toUpperCase() + message.slice(1);
  }
  return out;
}

/** Fields the form can see are missing before it asks the server: a required one left empty (a secret is optional when editing a saved channel). */
export function missing(spec: Spec, v: Values, editing: boolean): string[] {
  return spec.fields.filter((f) => f.required && !(v.fields[f.key] ?? "").trim() && !(editing && f.where === "secret")).map((f) => f.key);
}
