import { sharkBackend } from './sharkBackend';

/** Read a whole proposal artifact (the backend pages reads at 200 lines). */
export async function readArtifact(id: string | null) {
  if (!id) return '';
  let content = '', start = 1;
  for (let i = 0; i < 200; i++) {
    const page = await sharkBackend.readArtifact(id, start, 200);
    content += page.content;
    if (!page.truncated) break;
    start += 200;
  }
  return content;
}

export type DiffLine = { kind: 'same' | 'add' | 'del' | 'gap'; text: string; old?: number; new?: number };

/** Unified line diff (LCS), collapsed to `context` lines around each change. Bounded for chat previews. */
export function lineDiff(before: string, after: string, context = 2, limit = 1500): DiffLine[] | null {
  const a = before ? before.replace(/\n$/, '').split('\n') : [], b = after ? after.replace(/\n$/, '').split('\n') : [];
  if (a.length * b.length > limit * limit) return null;
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const all: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { all.push({ kind: 'same', text: a[i], old: i + 1, new: j + 1 }); i++; j++; }
    else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) { all.push({ kind: 'add', text: b[j], new: j + 1 }); j++; }
    else { all.push({ kind: 'del', text: a[i], old: i + 1 }); i++; }
  }
  const keep = all.map(() => false);
  all.forEach((l, k) => { if (l.kind !== 'same') for (let d = -context; d <= context; d++) if (all[k + d]) keep[k + d] = true; });
  const out: DiffLine[] = [];
  all.forEach((l, k) => { if (keep[k]) out.push(l); else if (out.at(-1)?.kind !== 'gap') out.push({ kind: 'gap', text: '' }); });
  return out;
}
