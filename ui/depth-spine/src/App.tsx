import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Workspace, type Ledger } from './components/Workspace';
import { drTimboBh01 } from './domain/sample';
import { drTimboSample, type WaterSample } from './domain/quality';
import type { Borehole } from './domain/types';
import {
  componentReady,
  isEmbedded,
  onRender,
  setComponentValue,
  setFrameHeight,
} from './streamlit/bridge';

export default function App() {
  const [borehole, setBorehole] = useState<Borehole>(drTimboBh01);
  const [sample, setSample] = useState<WaterSample>(drTimboSample);
  const root = useRef<HTMLDivElement>(null);

  // Streamlit hands the borehole and the analysis in as component args;
  // standalone falls back to the sample project.
  useEffect(() => {
    if (!isEmbedded()) return;
    const off = onRender((args) => {
      if (args.borehole) setBorehole(args.borehole as Borehole);
      if (args.sample) setSample(args.sample as WaterSample);
    });
    document.body.classList.add('embedded');
    componentReady();
    return off;
  }, []);

  // Keep the Streamlit iframe exactly as tall as the workspace.
  useLayoutEffect(() => {
    if (!isEmbedded() || !root.current) return;
    const el = root.current;
    const report = () => setFrameHeight(el.getBoundingClientRect().height);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className="page" ref={root}>
      <Workspace
        borehole={borehole}
        sample={sample}
        onLedgerChange={(ledger: Ledger) => setComponentValue(ledger)}
      />
    </div>
  );
}
