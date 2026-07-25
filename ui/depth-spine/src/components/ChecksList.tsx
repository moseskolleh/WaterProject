import type { Check } from '../domain/derive';

/** The live-checks list, shared by every stage's rail. */
export function ChecksList({ checks }: { checks: Check[] }) {
  return (
    <div className="checks">
      {checks.map((c) => (
        <div className="check" key={c.id}>
          <span className={`badge is-${c.status}`}>
            {c.status === 'ok' ? '✓' : '!'}
          </span>
          <span className="check-label">{c.label}</span>
          <span className={`check-value${c.status === 'warn' ? ' is-warn' : ''}`}>
            {c.value}
          </span>
        </div>
      ))}
    </div>
  );
}
