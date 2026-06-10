/**
 * markdown.ts
 * Secure Markdown rendering for educational video content.
 *
 * Renders:
 *   - AI-generated narration text (RefinedScript.narrationText)
 *   - Scene visual descriptions
 *   - Reviewer notes and correction notes
 *   - Feedback comments
 *
 * Security contract: ALL rendered HTML passes through sanitizeHtml()
 * before being returned. Never insert the output of renderMarkdown()
 * into the DOM without the { __html: ... } / dangerouslySetInnerHTML pattern,
 * and never bypass this layer to call marked.parse() directly.
 */

import { marked, type MarkedOptions } from "marked";

// -------------------------------------------------------------------------- //
// HTML escape (no external dependency needed)                                   //
// -------------------------------------------------------------------------- //

/**
 * Escape HTML special characters in a plain text string.
 * Use before inserting untrusted text into HTML context.
 *
 * @param text - Plain text to escape
 * @returns HTML-safe string
 *
 * @example
 *   escapeHtml('<script>alert(1)</script>') // '&lt;script&gt;alert(1)&lt;/script&gt;'
 */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g,  "&amp;")
    .replace(/</g,  "&lt;")
    .replace(/>/g,  "&gt;")
    .replace(/"/g,  "&quot;")
    .replace(/'/g,  "&#039;");
}

// -------------------------------------------------------------------------- //
// DOMPurify-based sanitiser (browser only)                                     //
// -------------------------------------------------------------------------- //

/** Allowed HTML tags for educational content. */
const ALLOWED_TAGS = [
  "h1","h2","h3","h4","h5","h6",
  "p","br","hr",
  "strong","em","code","pre",
  "ul","ol","li",
  "blockquote",
  "a",
  "table","thead","tbody","tr","th","td",
  "span","div",
  "sup","sub",
];

/** Allowed HTML attributes for educational content. */
const ALLOWED_ATTR = [
  "class","id",
  "href","target","rel",
  "colspan","rowspan",
];

/**
 * Sanitize an HTML string to prevent XSS.
 * Uses DOMPurify in browser environments.
 * Falls back to escapeHtml() during SSR (no DOM available).
 *
 * @param html - Potentially unsafe HTML string
 * @returns Sanitized HTML safe for dangerouslySetInnerHTML
 */
export function sanitizeHtml(html: string): string {
  if (typeof window === "undefined") {
    // SSR — no DOM, return escaped text
    return escapeHtml(html);
  }

  try {
    // DOMPurify is loaded as a browser-side dependency.
    // Access via window to avoid SSR import issues.
    const DOMPurify = (
      window as unknown as {
        DOMPurify?: {
          sanitize(dirty: string, config: Record<string, unknown>): string;
        };
      }
    ).DOMPurify;

    if (!DOMPurify?.sanitize) {
      if (process.env.NODE_ENV === "development") {
        console.warn("[markdown] DOMPurify not available — returning escaped HTML.");
      }
      return escapeHtml(html);
    }

    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS,
      ALLOWED_ATTR,
      ALLOW_DATA_ATTR:  false,
      FORBID_SCRIPTS:   true,
      FORBID_TAGS:      ["script","iframe","object","embed","form","input","button"],
    });
  } catch {
    return escapeHtml(html);
  }
}

// -------------------------------------------------------------------------- //
// Custom Marked renderer                                                        //
// -------------------------------------------------------------------------- //

/**
 * Build a custom Marked renderer with educational content typography.
 * Applies Tailwind classes inline — compatible with Tailwind v3 JIT.
 */
function createEduRenderer(): marked.Renderer {
  const renderer = new marked.Renderer();

  renderer.heading = function (text: string, level: 1 | 2 | 3 | 4 | 5 | 6): string {
    const classes: Record<number, string> = {
      1: "text-2xl font-bold text-gray-900 mt-6 mb-3",
      2: "text-xl font-semibold text-gray-900 mt-5 mb-2",
      3: "text-lg font-semibold text-gray-800 mt-4 mb-2",
      4: "text-base font-medium text-gray-800 mt-3 mb-1",
      5: "text-sm font-medium text-gray-700 mt-2 mb-1",
      6: "text-sm font-medium text-gray-600 mt-2 mb-1",
    };
    const cls = classes[level] ?? classes[3]!;
    const id  = text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    return `<h${level} id="${id}" class="${cls}">${text}</h${level}>\n`;
  };

  renderer.paragraph = function (text: string): string {
    return `<p class="text-gray-700 leading-relaxed mb-3">${text}</p>\n`;
  };

  renderer.codespan = function (code: string): string {
    return `<code class="bg-gray-100 text-indigo-700 px-1.5 py-0.5 rounded text-sm font-mono">${code}</code>`;
  };

  renderer.code = function (code: string, language?: string): string {
    const lang = language ?? "text";
    return (
      `<pre class="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto my-4 text-sm">` +
      `<code class="language-${lang} font-mono">${escapeHtml(code)}</code>` +
      `</pre>\n`
    );
  };

  renderer.blockquote = function (quote: string): string {
    return (
      `<blockquote class="border-l-4 border-indigo-400 pl-4 py-1 my-4 ` +
      `bg-indigo-50 rounded-r text-gray-700 italic">${quote}</blockquote>\n`
    );
  };

  renderer.list = function (body: string, ordered: boolean): string {
    const tag  = ordered ? "ol" : "ul";
    const cls  = ordered
      ? "list-decimal list-inside space-y-1 my-3 text-gray-700 pl-2"
      : "list-disc list-inside space-y-1 my-3 text-gray-700 pl-2";
    return `<${tag} class="${cls}">${body}</${tag}>\n`;
  };

  renderer.listitem = function (text: string): string {
    return `<li class="leading-relaxed">${text}</li>\n`;
  };

  renderer.hr = function (): string {
    return `<hr class="border-gray-200 my-6" />\n`;
  };

  renderer.strong = function (text: string): string {
    return `<strong class="font-semibold text-gray-900">${text}</strong>`;
  };

  renderer.em = function (text: string): string {
    return `<em class="italic text-gray-800">${text}</em>`;
  };

  renderer.link = function (
    href: string,
    _title: string | null,
    text: string
  ): string {
    const isExternal = /^https?:\/\//.test(href);
    const attrs      = isExternal ? ' target="_blank" rel="noopener noreferrer"' : "";
    return (
      `<a href="${href}"${attrs} ` +
      `class="text-indigo-600 hover:text-indigo-800 underline underline-offset-2">` +
      `${text}</a>`
    );
  };

  renderer.table = function (header: string, body: string): string {
    return (
      `<div class="overflow-x-auto my-4">` +
      `<table class="min-w-full divide-y divide-gray-200 border border-gray-200 rounded-lg">` +
      `<thead class="bg-gray-50">${header}</thead>` +
      `<tbody class="divide-y divide-gray-200 bg-white">${body}</tbody>` +
      `</table></div>\n`
    );
  };

  renderer.tablerow = function (content: string): string {
    return `<tr class="hover:bg-gray-50">${content}</tr>\n`;
  };

  renderer.tablecell = function (
    content: string,
    flags: { header?: boolean; align?: "center" | "left" | "right" | null }
  ): string {
    const tag       = flags.header ? "th" : "td";
    const alignCls  = flags.align ? `text-${flags.align}` : "text-left";
    const baseCls   = flags.header
      ? `px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide ${alignCls}`
      : `px-4 py-3 text-sm text-gray-700 ${alignCls}`;
    return `<${tag} class="${baseCls}">${content}</${tag}>`;
  };

  return renderer;
}

// -------------------------------------------------------------------------- //
// Marked configuration                                                          //
// -------------------------------------------------------------------------- //

const DEFAULT_MARKED_OPTIONS: MarkedOptions = {
  gfm:      true,   // GitHub Flavored Markdown (tables, strikethrough, task lists)
  breaks:   true,   // \n → <br> (important for narration text line breaks)
  pedantic: false,
};

// -------------------------------------------------------------------------- //
// Public render functions                                                       //
// -------------------------------------------------------------------------- //

/**
 * Render Markdown to sanitized HTML.
 * The primary rendering function — used everywhere educational content appears.
 *
 * @param markdown - Markdown string (may contain GFM syntax)
 * @returns Sanitized HTML safe for { __html: ... } / dangerouslySetInnerHTML
 *
 * @example
 *   const html = renderMarkdown("**Derivative**: rate of change of f(x)");
 *   // → '<p><strong class="...">Derivative</strong>: rate of change of f(x)</p>'
 */
export function renderMarkdown(markdown: string): string {
  if (!markdown?.trim()) return "";

  try {
    marked.use({
      renderer: createEduRenderer(),
      ...DEFAULT_MARKED_OPTIONS,
    });

    const raw = marked.parse(markdown) as string;
    return sanitizeHtml(raw);
  } catch (err) {
    if (process.env.NODE_ENV === "development") {
      console.error("[markdown] renderMarkdown error:", err);
    }
    return `<p class="text-gray-700">${escapeHtml(markdown)}</p>`;
  }
}

/**
 * Strip all Markdown formatting and return plain text.
 * Used for meta descriptions, search indices, subtitle content, clipboard.
 *
 * @param markdown - Markdown string
 * @returns Plain text with all Markdown syntax removed
 *
 * @example
 *   stripMarkdown("**Hello** _world_")   // "Hello world"
 *   stripMarkdown("# Title\n\nContent") // "Title Content"
 */
export function stripMarkdown(markdown: string): string {
  if (!markdown) return "";

  return markdown
    .replace(/^#{1,6}\s+/gm, "")                   // Headings
    .replace(/\*\*\*(.+?)\*\*\*/g, "$1")           // Bold-italic
    .replace(/\*\*(.+?)\*\*/g, "$1")               // Bold
    .replace(/__(.+?)__/g, "$1")                   // Bold (alt)
    .replace(/\*(.+?)\*/g, "$1")                   // Italic
    .replace(/_(.+?)_/g, "$1")                     // Italic (alt)
    .replace(/~~(.+?)~~/g, "$1")                   // Strikethrough
    .replace(/`{3}[\s\S]*?`{3}/g, "")             // Fenced code blocks
    .replace(/`(.+?)`/g, "$1")                     // Inline code
    .replace(/!\[.*?\]\(.+?\)/g, "")              // Images
    .replace(/\[(.+?)\]\(.+?\)/g, "$1")           // Links
    .replace(/^>\s+/gm, "")                        // Blockquotes
    .replace(/^[-*_]{3,}\s*$/gm, "")              // Horizontal rules
    .replace(/^[\s]*[-*+]\s+/gm, "")              // Unordered list markers
    .replace(/^[\s]*\d+\.\s+/gm, "")              // Ordered list markers
    .replace(/\n{3,}/g, "\n\n")                    // Collapse extra blank lines
    .replace(/[^\S\n]{2,}/g, " ")                  // Collapse horizontal whitespace
    .trim();
}

/**
 * Render scene narration text for display in the script editor or scene card.
 *
 * Narration is semi-structured:
 *   - May contain **bold** key terms
 *   - May contain `inline code` for formulas
 *   - Should NOT have complex heading structure
 *   - Newlines become paragraph breaks
 *
 * @param narrationText - Scene narration from RefinedScript.narrationText
 * @returns Sanitized HTML for dangerouslySetInnerHTML
 */
export function renderNarration(narrationText: string): string {
  if (!narrationText) return "";

  const preprocessed = narrationText
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^#{1,6}\s/gm, ""); // Strip heading markers — narration has no headings

  return renderMarkdown(preprocessed);
}

/**
 * Render reviewer notes or feedback comments.
 * More permissive than narration — allows headings, lists, and tables.
 *
 * @param text - Reviewer note or feedback comment
 * @returns Sanitized HTML for dangerouslySetInnerHTML
 */
export function renderReviewerNote(text: string): string {
  if (!text) return "";
  return renderMarkdown(text);
}

/**
 * Render a visual description as safe plain text in a paragraph.
 * Visual descriptions come from the LLM and may have inconsistent formatting —
 * we intentionally do not interpret Markdown here to avoid rendering artifacts.
 *
 * @param visualDescription - Scene visual description string
 * @returns Safe HTML paragraph for dangerouslySetInnerHTML
 */
export function renderVisualDescription(visualDescription: string): string {
  if (!visualDescription) return "";
  return `<p class="text-gray-600 text-sm leading-relaxed">${escapeHtml(visualDescription)}</p>`;
}

/**
 * Extract the first N sentences from Markdown/plain text.
 * Used for preview text in project cards and list views.
 *
 * @param text - Markdown or plain text
 * @param sentenceCount - Number of sentences to extract (default: 2)
 * @returns Plain text excerpt
 *
 * @example
 *   getExcerpt("First sentence. Second. Third.", 2) // "First sentence. Second."
 */
export function getExcerpt(text: string, sentenceCount = 2): string {
  const plain     = stripMarkdown(text);
  const sentences = plain.match(/[^.!?]+[.!?]+/g) ?? [];
  return sentences.slice(0, sentenceCount).join(" ").trim();
}

/**
 * Estimate reading time for a Markdown string.
 * Based on average adult reading speed of 200 wpm.
 *
 * @param markdown - Markdown string
 * @returns Estimated reading time in minutes (minimum 1)
 */
export function estimateReadingTime(markdown: string): number {
  const plain     = stripMarkdown(markdown);
  const wordCount = plain.split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.ceil(wordCount / 200));
}

/**
 * Check whether a string contains Markdown formatting syntax.
 * Use to decide between renderMarkdown() and plain text display.
 *
 * @param text - String to inspect
 * @returns true if Markdown syntax is detected
 */
export function containsMarkdown(text: string): boolean {
  const patterns = [
    /\*\*.+?\*\*/,    // Bold
    /_.+?_/,           // Italic
    /^#{1,6}\s/m,      // Heading
    /`[^`]+`/,         // Inline code
    /```[\s\S]+```/,   // Code block
    /\[.+?\]\(.+?\)/,  // Link
    /^[-*+]\s/m,       // Unordered list
    /^\d+\.\s/m,       // Ordered list
    /^>\s/m,           // Blockquote
    /^[-*_]{3,}$/m,    // Horizontal rule
  ];
  return patterns.some((p) => p.test(text));
}
