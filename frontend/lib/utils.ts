import { createCn } from "cn/config";

/** Our type scale (globals.css `--text-*`). Without this, `cn` reads e.g.
 * `text-body` as a text *color* and drops a real color class next to it:
 * `cn("text-primary-foreground", "text-body")` lost the color, which left the
 * Generate button's label the same color as its background. */
const FONT_SIZES = ["display", "h1", "h2", "h3", "h4", "body-lg", "body", "ui-label", "caption", "mono"];

export const cn = createCn({
  extend: { classGroups: { "font-size": [{ text: FONT_SIZES }] } },
});
