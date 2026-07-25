import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Workspace, type Ledger } from './components/Workspace';
import type { SpineView } from './domain/view';
import { readBakedPayload } from './streamlit/boot';
import {
  componentReady,
  isEmbedded,
  onRender,
  setComponentValue,
  setFrameHeight,
} from './streamlit/bridge';

/**
 * The component is a view. It receives a payload derived by the Python
 * package and sends back what the analyst did — the screen intervals they
 * moved, and the decisions they signed. It computes no hydrogeology.
 *
 * Rendered statically — one page with the payload baked in, which is how the
 * in-browser demo shows it — the same workspace is drawn, but the screens
 * cannot be edited: there is no Python on the other end to re-derive them.
 */
export default function App() {
  const baked = useMemo(readBakedPayload, []);
  const [view, setView] = useState<SpineView | null>(baked.view);
  const [busy, setBusy] = useState(false);
  const ledger = useRef<Ledger>({});
  const root = useRef<HTMLDivElement>(null);
  const isStatic = baked.mode === 'static';

  useEffect(() => {
    if (isStatic) return;
    const off = onRender((args) => {
      if (args.view) {
        setView(args.view as SpineView);
        // Whatever we asked for has come back derived.
        setBusy(false);
      }
    });
    document.body.classList.add('embedded');
    componentReady();
    return off;
  }, [isStatic]);

  useLayoutEffect(() => {
    if (isStatic || !isEmbedded() || !root.current) return;
    const el = root.current;
    const report = () => setFrameHeight(el.getBoundingClientRect().height);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, [view, isStatic]);

  const sendScreens = useCallback((screens: [number, number][] | null) => {
    setBusy(true);
    setComponentValue({ screens, ledger: ledger.current });
  }, []);

  const sendLedger = useCallback((next: Ledger) => {
    ledger.current = next;
    setComponentValue({ ledger: next });
  }, []);

  if (!view) {
    return (
      <div className="page" ref={root}>
        <div className="loading">Waiting for the analysis…</div>
      </div>
    );
  }

  return (
    <div className={`page${isStatic ? ' is-static' : ''}`} ref={root}>
      <Workspace
        view={view}
        busy={busy}
        readOnly={isStatic}
        onScreens={sendScreens}
        onLedgerChange={sendLedger}
      />
    </div>
  );
}
