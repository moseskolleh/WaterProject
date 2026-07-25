/**
 * Minimal Streamlit custom-component bridge.
 *
 * Implements the postMessage protocol directly rather than pulling in
 * streamlit-component-lib, so the same bundle runs standalone (where the
 * messages simply go nowhere) and inside Streamlit.
 */

const API_VERSION = 1;

type RenderHandler = (args: Record<string, unknown>, theme?: unknown) => void;

/** True when the page is inside an iframe — i.e. possibly a Streamlit host. */
export function isEmbedded(): boolean {
  try {
    return window.parent !== window;
  } catch {
    return true;
  }
}

function post(type: string, payload: Record<string, unknown> = {}) {
  if (!isEmbedded()) return;
  window.parent.postMessage(
    { isStreamlitMessage: true, type, ...payload },
    '*',
  );
}

export function componentReady() {
  post('streamlit:componentReady', { apiVersion: API_VERSION });
}

export function setFrameHeight(height: number) {
  post('streamlit:setFrameHeight', { height: Math.ceil(height) });
}

/** Return a value to the Python side; it becomes the component's return value. */
export function setComponentValue(value: unknown) {
  post('streamlit:setComponentValue', { value, dataType: 'json' });
}

/** Subscribe to render messages. Returns an unsubscribe function. */
export function onRender(handler: RenderHandler): () => void {
  const listener = (event: MessageEvent) => {
    const data = event.data;
    if (!data || data.type !== 'streamlit:render') return;
    handler((data.args ?? {}) as Record<string, unknown>, data.theme);
  };
  window.addEventListener('message', listener);
  return () => window.removeEventListener('message', listener);
}
