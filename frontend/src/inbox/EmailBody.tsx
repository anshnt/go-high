import { ImageOff } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { emailDocument } from "./emailHtml.ts";
import { hasRemoteImages } from "./text.ts";
import { MessageText } from "./MessageText";

/**
 * An email, drawn safely: its HTML is cleaned and shown in a sandboxed frame (no scripts) under a policy that blocks every
 * request, and remote images stay out until the person asks ("Show images"). Without HTML, the plain text.
 */
export function EmailBody({ html, body, q }: { html: string | null; body: string; q: string }) {
  const [images, setImages] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  const clean = useMemo(() => (html ? emailDocument(html, { images }) : null), [html, images]);
  const remote = hasRemoteImages(html);

  const fit = () => {
    const f = frame.current;
    const doc = f?.contentDocument;
    if (!f || !doc) return;
    const set = () => (f.style.height = `${Math.ceil(doc.documentElement.scrollHeight)}px`);
    set();
    doc.addEventListener("load", set, true); // images that arrive later change the height
    new ResizeObserver(set).observe(doc.body);
  };

  if (!clean) return <MessageText text={body} q={q} className="ib-text" />;
  return (
    <div className="ib-email-body">
      {remote && !images && (
        <div className="ib-img-bar">
          <ImageOff size={14} aria-hidden />
          <span>Images are not loaded, so the sender cannot see that you read this.</span>
          <button type="button" onClick={() => setImages(true)}>
            Show images
          </button>
        </div>
      )}
      {remote && images && (
        <div className="ib-img-bar">
          <span>Images are shown.</span>
          <button type="button" onClick={() => setImages(false)}>
            Hide images
          </button>
        </div>
      )}
      {/* no allow-scripts: nothing inside can run. allow-same-origin only lets us measure the height, and open links in a new tab. */}
      <iframe ref={frame} className="ib-frame" title="Email content" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" srcDoc={clean.srcdoc} onLoad={fit} />
    </div>
  );
}
