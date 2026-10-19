import type { ChannelKind } from "../inbox/types.ts";

// The conversations of the public demo: fictional threads for Acme Agency, tied to contacts of the demo CRM (they are
// picked from the same seeded data, in order, by what the channel needs: a phone number, an email address). `{n}` is
// the contact's first name. Nothing here is real: example domains, 555 numbers, no brands, no secrets.

/** [direction, minutes after the message before it, text, extras]. `note` is an internal note, `sys` a system line. */
export type Msg = [dir: "in" | "out" | "note" | "sys", gap: number, text: string, extra?: { subject?: string; html?: string; files?: [name: string, type: string][]; by?: string; failed?: string }];

export type Scenario = {
  ch: ChannelKind;
  /** Minutes ago that the last message happened. */
  ago: number;
  status?: "snoozed" | "closed";
  /** The assignee: a first name of the team (maya, theo, priya, diego, sam, hana), "me", or nobody. */
  who?: string;
  team?: "support" | "sales";
  /** Not yet read by the signed-in user. */
  unread?: boolean;
  /** A snoozed conversation comes back after this many minutes from now. */
  until?: number;
  /** What the contact has agreed to for this channel. */
  consent?: "stop" | "dnd";
  /** Quiet hours apply to this contact whenever you start the conversation. */
  quiet?: boolean;
  msgs: Msg[];
};

const LOGO_MAIL = (name: string, lines: string) => `<div style="font-family:Arial,sans-serif;font-size:14px;color:#222"><p>${lines}</p><p>Best,<br><strong>${name}</strong></p><p><img src="__LOGO__" alt="Acme Agency" width="120" height="32"></p></div>`;

export const SCENARIOS: Scenario[] = [
  // ---- SMS ----
  { ch: "sms", ago: 3, unread: true, msgs: [["out", 0, "Hi {n}, confirming kickoff for the website rebuild on Thursday at 10:00. Does that still suit you?"], ["in", 380, "Hi, this is {n}. Are we still on for Thursday? Can we make it 11:00 instead?"]] },
  { ch: "sms", ago: 22, who: "me", msgs: [["in", 0, "Can I get the proposal today? My partner wants to look at it tonight."], ["out", 4, "Sure {n}, sending it over by 3pm."], ["in", 2, "Perfect, thanks!"], ["out", 1, "Done. It is in your inbox now, with two package options."]] },
  { ch: "sms", ago: 47, unread: true, team: "support", msgs: [["in", 0, "Our search listing shows the wrong opening hours."], ["in", 3, "Also the phone number is the old one."], ["in", 2, "Can you fix that this week? Customers keep calling the old line."]] },
  { ch: "sms", ago: 1500, status: "closed", who: "maya", msgs: [["in", 0, "Invoice 1043 paid just now!"], ["out", 12, "Got it, thank you {n}. Receipt is on its way."], ["in", 3, "Great, thanks for the quick turnaround."]] },
  { ch: "sms", ago: 4310, who: "me", consent: "stop", msgs: [["out", 0, "Reminder from Acme Agency: your onboarding call is tomorrow at 10:00. Reply YES to confirm."], ["sys", 90, "{n} replied STOP and opted out of SMS."], ["sys", 0, "Auto reply sent: You are unsubscribed from Acme Agency texts. Reply START to resubscribe."]] },
  { ch: "sms", ago: 800, status: "snoozed", until: 1100, who: "priya", msgs: [["in", 0, "Can you call me next week? I am travelling until Monday."], ["out", 15, "Of course {n}. I will ring you Tuesday morning."], ["note", 1, "Snoozed until Tuesday: they are travelling, call after 9:00.", { by: "priya" }]] },
  { ch: "sms", ago: 95, who: "theo", unread: true, msgs: [["out", 0, "Hi {n}, your quarterly report is ready. Want to walk through it on Friday?", { failed: "Carrier rejected the message (error 30007). Check the number and try again." }], ["in", 70, "Hello? I did not get your text. Is the report ready?"]] },
  { ch: "sms", ago: 180, msgs: [["in", 0, "Do you offer payment plans for the annual retainer?"], ["out", 25, "We do, over 3 or 6 months with no fees."], ["in", 40, "Great, 6 months then. How do I sign up?"]] },
  { ch: "sms", ago: 3000, status: "closed", who: "sam", msgs: [["in", 0, "Thanks for the quick fix on the contact form!"], ["out", 9, "Anytime {n}. Shout if anything else looks odd."]] },
  { ch: "sms", ago: 8, who: "me", unread: true, msgs: [["in", 0, "Is the campaign live yet?"], ["in", 4, "I am seeing zero leads so far, is that normal for day one?"]] },
  { ch: "sms", ago: 600, who: "diego", consent: "dnd", msgs: [["out", 0, "Quick check in about your Q4 plan. Do you have 10 minutes this week?"], ["in", 120, "Not now please, we are in the middle of a move."], ["note", 5, "Do not disturb on for SMS at their request. Email only until they say otherwise.", { by: "diego" }]] },
  { ch: "sms", ago: 1900, msgs: [["in", 0, "Hi, I got your flyer. What do you charge for local listings and reviews?"], ["out", 14, "Hi {n}! Packages start at $450 a month. Want a quick call to see what fits?"], ["in", 50, "Yes, tomorrow afternoon works."]] },
  { ch: "sms", ago: 2600, who: "hana", team: "sales", msgs: [["out", 0, "Hi {n}, can we move our Friday call to Monday?"], ["in", 30, "Monday is tricky, mornings are packed."], ["out", 5, "How about Monday 15:30?"], ["in", 8, "That works."], ["out", 1, "Booked. You will get a calendar invite shortly."], ["in", 2, "Got it, see you then."]] },
  { ch: "sms", ago: 2900, quiet: true, msgs: [["in", 0, "Hi, I am in Sydney so apologies for the odd hours. Could you send the brand guide?"]] },

  // ---- Email ----
  { ch: "email", ago: 12, unread: true, msgs: [["in", 0, "Hi team,\n\nWe are looking at three landing pages for the spring launch: one for the main offer, one for the referral program and one for the waitlist. Could you send a quote and a rough timeline?\n\nWe would like to start in two weeks if possible.\n\nThanks,\n{n}", { subject: "Quote request: 3 landing pages" }]] },
  { ch: "email", ago: 75, unread: true, team: "sales", msgs: [["in", 0, "Hello,\n\nI am a studio owner and would like to explore a partnership: we send you clients who need websites, you refer clients who need photography.\n\nWould you be open to a short call?\n\n{n}", { subject: "Partnership opportunity" }]] },
  { ch: "email", ago: 300, who: "me", msgs: [["in", 0, "Hi,\n\nQuick question about the reporting add-on: does it include call tracking, or only form leads?\n\n{n}", { subject: "Question about the reporting add-on" }], ["out", 60, "Hi {n}, thanks for asking. The add-on covers form leads, calls and booked appointments in one dashboard. Call tracking needs a tracking number, which we set up for you.\n\nHappy to show it on a call.", { subject: "Re: Question about the reporting add-on", html: LOGO_MAIL("Alex Rivera", "Hi {n}, thanks for asking. The add-on covers <strong>form leads, calls and booked appointments</strong> in one dashboard. Call tracking needs a tracking number, which we set up for you.<br><br>Happy to show it on a call.") }], ["in", 90, "That helps, thank you. Let us do the call next week.", { subject: "Re: Question about the reporting add-on" }]] },
  { ch: "email", ago: 520, status: "snoozed", until: 2900, who: "priya", msgs: [["out", 0, "Hi {n}, attached is the agreement for the annual retainer. Sign whenever you are ready.", { subject: "Contract for signature", files: [["Agreement-annual-retainer.pdf", "application/pdf"]] }], ["in", 180, "Thanks. Our finance lead is out until next week, I will sign when she is back.", { subject: "Re: Contract for signature" }], ["note", 2, "Waiting on their finance lead. Snoozed until the 24th.", { by: "priya" }]] },
  { ch: "email", ago: 2000, who: "theo", msgs: [["in", 0, "Hi,\n\nNotes and the screenshot from today's call are attached. The header on the pricing page is the thing we would fix first.\n\n{n}", { subject: "Meeting notes and screenshot", files: [["meeting-notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"], ["pricing-header.png", "image/png"]] }], ["out", 120, "Thanks {n}, that is clear. We will fix the header this week and send a preview link.", { subject: "Re: Meeting notes and screenshot" }]] },
  { ch: "email", ago: 5000, status: "closed", msgs: [["in", 0, "Thanks for the great work on the launch!\n\n{n}", { subject: "Thanks!" }], ["out", 40, "Thank you {n}, it was a pleasure. We will check the numbers again in two weeks.", { subject: "Re: Thanks!" }]] },
  { ch: "email", ago: 140, unread: true, team: "support", msgs: [["in", 0, "Hi,\n\nI cannot log in to the client portal. I have tried:\n- the reset link twice\n- a different browser\n- my phone\n\nNothing arrives in my inbox.\n\n{n}", { subject: "Login not working" }]] },
  { ch: "email", ago: 700, who: "sam", msgs: [["in", 0, "Hi, we would like to renew the Pro plan for another year. Is the price the same?\n\n{n}", { subject: "Re: Pro plan renewal" }], ["note", 20, "Price is unchanged for existing clients until January. Ask Maya about the 10% loyalty discount.", { by: "sam" }], ["out", 25, "Hi {n}, yes, the price is unchanged until January. Shall I send the renewal?", { subject: "Re: Pro plan renewal" }]] },
  { ch: "email", ago: 4000, msgs: [["in", 0, "Hi,\n\nThe newsletter was fine but the button was too small on my phone. Could you make it bigger next time?\n\n{n}", { subject: "Newsletter feedback" }]] },
  { ch: "email", ago: 2900, status: "closed", who: "hana", msgs: [["in", 0, "Hello,\n\nCould you resend invoice 1043? I cannot find it.\n\n{n}", { subject: "Invoice 1043" }], ["out", 18, "Hi {n}, invoice 1043 is attached again.", { subject: "Re: Invoice 1043", files: [["invoice-1043.pdf", "application/pdf"]] }], ["in", 30, "Got it, thanks.", { subject: "Re: Invoice 1043" }]] },
  { ch: "email", ago: 200, who: "me", msgs: [["in", 0, "", { subject: "Feedback on the website draft", html: `<div style="font-family:Arial,sans-serif;font-size:14px;color:#222"><p>Hi team,</p><p>We looked at the draft and like the direction. Three things:</p><ul><li>The <strong>hero image</strong> feels too dark</li><li>Can the contact form sit higher on the page?</li><li>We need the <em>refund policy</em> linked in the footer</li></ul><p>Thanks,<br><strong>{n}</strong></p><hr><p style="font-size:12px;color:#666"><img src="__LOGO__" alt="Studio logo" width="120" height="32"><br>Sent from my phone</p></div>` }], ["out", 100, "Thanks {n}, all three are easy. We will send a new draft tomorrow.", { subject: "Re: Feedback on the website draft" }]] },
  { ch: "email", ago: 90, unread: true, msgs: [["in", 0, "Hi,\n\nIs there a way to pause the monthly plan for two months while we renovate? We would be back in November.\n\nThank you,\n{n}", { subject: "Pausing the monthly plan" }]] },
  { ch: "email", ago: 3400, status: "closed", who: "maya", msgs: [["in", 0, "Hi,\n\nI was charged twice in September. Please refund one of them.\n\n{n}", { subject: "Refund request" }], ["note", 30, "Confirmed in billing: duplicate charge on the 14th. Refunding.", { by: "maya" }], ["out", 15, "Hi {n}, you are right, there was a duplicate charge. The refund is on its way and should arrive in 3 to 5 days.", { subject: "Re: Refund request" }], ["in", 220, "Perfect, thank you for fixing it so fast.", { subject: "Re: Refund request" }]] },

  // ---- WhatsApp ----
  { ch: "whatsapp", ago: 5, unread: true, msgs: [["in", 0, "Hi! I saw your ad. Can you help with an online store for my bakery?"], ["in", 1, "We sell about 40 products, mostly cakes and bread."]] },
  { ch: "whatsapp", ago: 70, who: "me", msgs: [["in", 0, "Good morning, the photos you sent look great."], ["out", 12, "Glad you like them {n}! Shall we use them on the homepage?"], ["in", 20, "Yes please, and the third one for the menu page."]] },
  { ch: "whatsapp", ago: 1300, status: "closed", who: "diego", msgs: [["in", 0, "Thank you, the booking works perfectly now."], ["out", 5, "Great to hear it {n}!"]] },
  { ch: "whatsapp", ago: 33, unread: true, team: "sales", msgs: [["in", 0, "Hello, how much is a full rebrand for a small clinic?"]] },
  { ch: "whatsapp", ago: 2200, who: "hana", msgs: [["out", 0, "Hi {n}, here is the voice note summary: logo in two versions, colours unchanged.", {}], ["in", 400, "Perfect. Please send the final files tomorrow.", {}]] },
  { ch: "whatsapp", ago: 900, status: "snoozed", until: 380, who: "theo", msgs: [["in", 0, "Can we talk about the second payment next week? We are short this month."], ["out", 20, "No problem {n}, I will check in on Monday."]] },
  { ch: "whatsapp", ago: 410, msgs: [["in", 0, "Do you work on Saturdays? I can only talk then."], ["out", 60, "We can do Saturday mornings for calls. Which time works?"], ["in", 100, "10:00 would be great."]] },

  // ---- Web chat ----
  { ch: "webchat", ago: 2, unread: true, msgs: [["in", 0, "Hi, quick question about pricing before I book a call."], ["in", 1, "Is the setup fee included in the monthly price?"]] },
  { ch: "webchat", ago: 18, unread: true, team: "support", msgs: [["in", 0, "Hello? Is anyone there?"]] },
  { ch: "webchat", ago: 60, who: "me", msgs: [["in", 0, "Hi, I want to cancel my Thursday appointment."], ["out", 3, "Hi {n}, no problem. Would you like to rebook for next week?"], ["in", 2, "Yes, Tuesday at the same time please."], ["out", 2, "Done, Tuesday at 10:00 is booked."]] },
  { ch: "webchat", ago: 1100, status: "closed", who: "priya", msgs: [["in", 0, "Do you integrate with my booking calendar?"], ["out", 6, "Yes, it syncs both ways. Want a walkthrough?"], ["in", 3, "No thanks, that is all I needed."]] },
  { ch: "webchat", ago: 240, msgs: [["in", 0, "How long does a website rebuild take?"], ["out", 8, "Usually 4 to 6 weeks, depending on how many pages you have. How many are you planning?"], ["in", 12, "Around 12 pages."]] },
  { ch: "webchat", ago: 3600, who: "sam", msgs: [["in", 0, "Can I see examples of your work in healthcare?"], ["out", 20, "Of course {n}. I will email three case studies today."]] },
  { ch: "webchat", ago: 130, team: "sales", unread: true, msgs: [["in", 0, "Can I speak to someone about the agency partnership plan?"]] },
];
