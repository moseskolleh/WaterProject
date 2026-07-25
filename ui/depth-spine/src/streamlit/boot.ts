import type { SpineView } from '../domain/view';

/**
 * How this instance was rendered.
 *
 * `component` - the Streamlit custom component: the payload arrives by
 *   postMessage and edits go back to Python, which re-derives them.
 * `static` - one self-contained page with the payload baked in, used where
 *   there is no server to serve a component from. Draws the same workspace;
 *   the screen handles are inert because there is nothing to send them to.
 */
export type Mode = 'component' | 'static';

export interface Boot {
  mode: Mode;
  view: SpineView | null;
}

/** Read the payload baked into the page, if this is a static render. */
export function readBakedPayload(): Boot {
  const node = document.getElementById('spine-data');
  if (!node?.textContent) return { mode: 'component', view: null };
  try {
    const parsed = JSON.parse(node.textContent) as {
      view: SpineView;
      interactive?: boolean;
    };
    return {
      mode: parsed.interactive ? 'component' : 'static',
      view: parsed.view ?? null,
    };
  } catch {
    // An unrendered template leaves the placeholder in place, which is not
    // JSON. Fall back to the component path rather than showing a broken page.
    return { mode: 'component', view: null };
  }
}
