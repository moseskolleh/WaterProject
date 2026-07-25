/**
 * The sign-off layer (direction 2b), as a layer rather than a shell.
 *
 * Every stage produces one professional opinion. The toolkit recommends it, a
 * named person accepts or overrides it, and an override carries a reason that
 * travels into the report. That is the whole ledger — no second application.
 */

export type StageId = 'design' | 'quality' | 'costing';

export type DecisionStatus = 'pending' | 'accepted' | 'overridden';

export interface DecisionRecord {
  stage: StageId;
  status: Exclude<DecisionStatus, 'pending'>;
  /** What was certified — the recommended figure, or the override. */
  value: string;
  /** The toolkit's recommendation, kept even when overridden. */
  recommended: string;
  /** Required when status is 'overridden'. */
  reason?: string;
  signatory: string;
  at: string;
  /** False when the person signed off over an outstanding flag. */
  clean: boolean;
}

export const SIGNATORY = 'M. Kolleh · hydrogeologist';

export function timestamp(): string {
  return new Date().toISOString().slice(0, 16).replace('T', ' ');
}

export const STAGES: { id: StageId; label: string }[] = [
  { id: 'design', label: 'Design' },
  { id: 'quality', label: 'Water quality' },
  { id: 'costing', label: 'Costing & BoQ' },
];
