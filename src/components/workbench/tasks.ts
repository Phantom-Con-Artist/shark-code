import type { ProjectEntry } from '../../stores/useProjectStore';

export type TaskGroup = 'build' | 'test' | 'run' | 'other';
export type WorkspaceTask = { id: string; label: string; command: string; group: TaskGroup; source: string };

function groupOf(name: string): TaskGroup {
  const n = name.toLowerCase();
  if (/(^|:)(build|compile|bundle|package|dist|tsc)/.test(n)) return 'build';
  if (/(test|spec|check|lint|clippy|typecheck|e2e)/.test(n)) return 'test';
  if (/(dev|start|serve|preview|run|watch|tauri)/.test(n)) return 'run';
  return 'other';
}

/** Detect build, test and run tasks the way VS Code's auto-detection does, from project manifests. */
export async function detectTasks(entries: ProjectEntry[], read: (path: string) => Promise<string | null>): Promise<WorkspaceTask[]> {
  const has = (p: string) => entries.some(e => e.path === p && !e.directory);
  const tasks: WorkspaceTask[] = [];
  const add = (label: string, command: string, source: string, group = groupOf(label)) => tasks.push({ id: `${source}:${label}`, label, command, group, source });

  if (has('package.json')) {
    try {
      const pkg = JSON.parse((await read('package.json')) ?? '{}') as { scripts?: Record<string, string> };
      const pm = has('pnpm-lock.yaml') ? 'pnpm' : has('yarn.lock') ? 'yarn' : has('bun.lockb') || has('bun.lock') ? 'bun' : 'npm';
      if (!entries.some(e => e.path === 'node_modules')) add('install', `${pm} install`, pm, 'other');
      for (const name of Object.keys(pkg.scripts ?? {})) add(name, pm === 'npm' ? `npm run ${name}` : `${pm} ${name}`, pm);
    } catch { /* malformed package.json: nothing to offer */ }
  }
  if (has('Cargo.toml')) for (const [l, c] of [['build', 'cargo build'], ['test', 'cargo test'], ['run', 'cargo run'], ['clippy', 'cargo clippy'], ['fmt', 'cargo fmt']]) add(l, c, 'cargo');
  if (has('go.mod')) for (const [l, c] of [['build', 'go build ./...'], ['test', 'go test ./...'], ['run', 'go run .'], ['vet', 'go vet ./...']]) add(l, c, 'go');
  if (has('pyproject.toml') || has('requirements.txt') || has('setup.py')) {
    const runner = has('uv.lock') ? 'uv run ' : has('poetry.lock') ? 'poetry run ' : 'python -m ';
    add('test', `${runner}pytest`, 'python', 'test');
  }
  for (const make of ['Makefile', 'makefile']) if (has(make)) {
    const text = (await read(make)) ?? '';
    const targets = [...text.matchAll(/^([A-Za-z0-9][\w.-]*)\s*:(?!=)/gm)].map(m => m[1]).filter(t => !t.startsWith('.'));
    for (const t of [...new Set(targets)].slice(0, 30)) add(t, `make ${t}`, 'make');
  }
  return tasks;
}

export function defaultTask(tasks: WorkspaceTask[], group: TaskGroup) {
  return tasks.find(t => t.group === group && /^(build|test)$/.test(t.label)) ?? tasks.find(t => t.group === group);
}
