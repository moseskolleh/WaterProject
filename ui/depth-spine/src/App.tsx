import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Workspace, type Ledger } from './components/Workspace';
import type { SpineView } from './domain/view';
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
 */
export default function App() {
  const [view, setView] = useState<SpineView | null>(null);
  const [busy, setBusy] = useState(false);
  const ledger = useRef<Ledger>({});
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
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
  }, []);

  useLayoutEffect(() => {
    if (!isEmbedded() || !root.current) return;
    const el = root.current;
    const report = () => setFrameHeight(el.getBoundingClientRect().height);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, [view]);

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
    <div className="page" ref={root}>
      <Workspace
        view={view}
        busy={busy}
        onScreens={sendScreens}
        onLedgerChange={sendLedger}
      />
    </div>
  );
}
