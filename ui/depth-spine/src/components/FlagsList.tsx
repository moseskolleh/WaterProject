import type { Flag } from '../domain/view';

const GLYPH: Record<Flag['level'], string> = {
  info: 'i',
  warning: '!',
  error: '!',
};

/**
 * The toolkit's own DataFlags, rendered as they are.
 *
 * These are the same objects the reports carry, so what the analyst sees on
 * screen is exactly what a reviewer will read in the .docx — including the
 * codes, which is how a flag gets discussed over the phone.
 */
export function FlagsList({ flags, empty }: { flags: Flag[]; empty: string }) {
  if (flags.length === 0) {
    return (
      <div className="checks">
        <div className="check">
          <span className="badge is-ok">✓</span>
          <span className="check-label">{empty}</span>
        </div>
      </div>
    );
  }
  return (
    <div className="checks">
      {flags.map((f, i) => (
        <div className="check is-stacked" key={`${f.code}-${i}`}>
          <span className={`badge is-${f.level}`}>{GLYPH[f.level]}</span>
          <div className="check-body">
            <div className="check-label">{f.message}</div>
            <div className="check-code">
              {f.code}
              {f.context && ` · ${f.context}`}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
