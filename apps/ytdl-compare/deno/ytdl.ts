#!/usr/bin/env -S deno run --allow-run --allow-read --allow-write
/**
 * ytdl.ts — YouTube downloader orchestrator, Deno/TypeScript comparison build.
 *
 * Same subcommands, same option surface, same decision logic as the Operon
 * edition (apps/ytdl/ytdl.op). `selfcheck` prints the decision matrix that
 * must be byte-identical across all three builds — the differential pin.
 *
 * Engines: yt-dlp + ffmpeg from PATH (aria2c optional). Zero npm deps.
 *
 * The shared decision core (types, formatting, engine probes, selector
 * logic, format table, download loop, option layer) lives in lib.ts —
 * split out 2026-11-21 so every file stays under the
 * complexity/file-too-large 400-line limit.
 *
 * run: deno run --allow-run --allow-read --allow-write ytdl.ts <cmd> ...
 */

import {
  AUDIO_KINDS,
  Meta,
  Opts,
  RunResult,
  TIERS,
  detectTools,
  die,
  download,
  getOpts,
  hOf,
  infoLines,
  mget,
  report,
  runProg,
  selectionArgs,
  tableRows,
  tailLines,
  tOf,
  toolLine,
} from "./lib.ts";

// ---------------------------------------------------------- commands

async function cmdDoctor(): Promise<never> {
  const t = await detectTools();
  console.log("ytdl doctor — probing PATH engines");
  let ytdlpOk = false;
  let ffmpegOk = false;
  if (t.ytdlp) {
    ytdlpOk = true;
    console.log(`  yt-dlp   ${t.ytdlp}  [required: present]`);
  } else {
    console.log("  yt-dlp   MISSING  [required: pip install yt-dlp or brew install yt-dlp]");
  }
  if (t.ffmpeg) {
    ffmpegOk = true;
    console.log(`  ffmpeg   ${t.ffmpeg}  [required: present]`);
  } else {
    console.log("  ffmpeg   MISSING  [required: apt/brew install ffmpeg]");
  }
  if (t.aria2) {
    console.log(`  aria2c   ${t.aria2}  [optional: multi-connection downloads]`);
  } else {
    console.log("  aria2c   not found  [optional: apt/brew install aria2 for 16-connection accel]");
  }
  if (ytdlpOk && ffmpegOk) {
    console.log("verdict: READY — deno runtime + PATH engines");
    Deno.exit(0);
  }
  console.log("verdict: NOT READY — missing required engine(s)");
  Deno.exit(1);
}

async function cmdInfo(rest: string[]): Promise<never> {
  const o = getOpts(rest);
  if (!o.url) die("error: info needs a URL");
  let r: RunResult;
  try {
    r = await runProg("yt-dlp", ["-J", "--no-playlist", o.url]);
  } catch (e) {
    die(`yt-dlp denied — ${(e as Error).message}`, 1);
  }
  if (r.code !== 0) {
    console.log(`yt-dlp failed (code ${r.code}):`);
    console.log(tailLines(r.stderr, 3));
    Deno.exit(1);
  }
  const meta = JSON.parse(r.stdout) as Meta;
  for (const ln of infoLines(meta)) console.log(ln);
  Deno.exit(0);
}

async function cmdGet(rest: string[]): Promise<never> {
  const o = getOpts(rest);
  o.aria2_ok = (await toolLine("aria2c", "--version")) !== "";
  if (!o.url) die("error: get needs a URL");
  console.log(`ytdl[deno]: get ${o.url}`);
  console.log(`  out=${o.out}  selector: ${selectionArgs(o).join(" ")}`);
  Deno.mkdirSync(o.out, { recursive: true });
  const d = await download(o.url, o);
  report(d);
  Deno.exit(d.ok ? 0 : 1);
}

async function cmdQueue(rest: string[]): Promise<never> {
  if (!rest.length || rest[0].startsWith("--")) {
    die("error: queue needs a file (one URL per line, # comments)");
  }
  const file = rest[0];
  const o = getOpts(rest.slice(1));
  o.aria2_ok = (await toolLine("aria2c", "--version")) !== "";
  let text: string;
  try {
    text = Deno.readTextFileSync(file);
  } catch (e) {
    die(`error: cannot read queue file ${file} (${(e as Error).message})`);
  }
  const urls = text.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("#"));
  const jobs = Math.max(1, Math.min(o.jobs, urls.length));
  const rows: string[] = [];
  if (jobs === 1) {
    for (const u of urls) {
      const d = await download(u, o);
      rows.push(`${d.ok ? "ok" : "FAIL"}\t${d.attempts}\t${u}`);
    }
  } else {
    const chunks: string[][] = Array.from({ length: jobs }, () => []);
    urls.forEach((u, idx) => chunks[idx % jobs].push(u));
    // run chunks concurrently on the event loop (async downloads interleave)
    const results = await Promise.all(chunks.map(async (chunk) => {
      const out: string[] = [];
      for (const u of chunk) {
        const d = await download(u, o);
        out.push(`${d.ok ? "ok" : "FAIL"}\t${d.attempts}\t${u}`);
      }
      return out;
    }));
    for (const chunk of results) rows.push(...chunk);
  }
  let failures = 0;
  for (const r of rows) {
    console.log(r);
    if (!r.startsWith("ok\t")) failures += 1;
  }
  console.log(`queue: ${rows.length} items, ${failures} failed (workers: ${jobs})`);
  Deno.exit(failures > 0 ? 1 : 0);
}

function cmdSelfcheck(rest: string[]): never {
  if (!rest.length) die("error: selfcheck needs a fixture .json path");
  const meta = JSON.parse(Deno.readTextFileSync(rest[0])) as Meta;
  for (const q of ["best", ...TIERS]) {
    const o: Partial<Opts> = { quality: q, audio: "", fmt: "" };
    console.log(`q=${q} a=- :: ${selectionArgs(o).join(" ")}`);
  }
  for (const kind of AUDIO_KINDS) {
    const o: Partial<Opts> = { quality: "best", audio: kind, fmt: "" };
    console.log(`q=- a=${kind} :: ${selectionArgs(o).join(" ")}`);
  }
  const fs = (meta.formats ?? []).slice().sort((a, b) => {
    if (hOf(a) > hOf(b)) return -1;
    if (hOf(a) < hOf(b)) return 1;
    return tOf(a) > tOf(b) ? -1 : 1;
  });
  console.log(`sort-check: ${fs.map((f) => String(f.format_id)).join(",")}`);
  const h = infoLines(meta);
  console.log(`hdr-check: ${h[0]}`);
  console.log(`hdr-check: ${h[1]}`);
  Deno.exit(0);
}

// ---------------------------------------------------------- deep bench
// Uniform workloads for the cross-language deep benchmark
// (docs/BENCHMARK-DEEP.md, harness: scripts/bench_deep.py). Each prints
// ONE "bench-* cs=..." line; cs must be byte-identical in every build.

function benchArg(rest: string[], name: string, def: string): string {
  const f = `--${name}`;
  for (let i = 0; i < rest.length; i++) {
    if (rest[i] === f && i + 1 < rest.length) return rest[i + 1];
    if (rest[i].startsWith(f + "=")) return rest[i].slice(f.length + 1);
  }
  return def;
}

function progressLine(i: number): string {
  const pp = String((i * 7) % 100).padStart(2, "0");
  const ss = String((i * 3) % 60).padStart(2, "0");
  return `[download]  ${pp}% of 12.00MiB at 2.00MiB/s ETA 00:${ss}`;
}

function cmdBenchStartup(): never {
  console.log("ytdl-bench ready");
  Deno.exit(0);
}

function cmdBenchJson(rest: string[]): never {
  if (!rest.length) die("error: bench-json needs a fixture path");
  const n = parseInt(benchArg(rest, "n", "100"));
  const text = Deno.readTextFileSync(rest[0]);
  const meta = JSON.parse(text) as Meta;
  let nf = 0;
  let title = "";
  for (let i = 0; i < n; i++) {
    const m = JSON.parse(text) as Meta;
    nf = (m.formats ?? []).length;
    title = mget(m, "title");
  }
  if (n > 0 && nf !== (meta.formats ?? []).length) {
    console.log("bench-json MISMATCH");
    Deno.exit(1);
  }
  console.log(`bench-json cs=${title}:${nf}:${n}`);
  Deno.exit(0);
}

function cmdBenchTable(rest: string[]): never {
  if (!rest.length) die("error: bench-table needs a fixture path");
  const rounds = parseInt(benchArg(rest, "rounds", "20"));
  const meta = JSON.parse(Deno.readTextFileSync(rest[0])) as Meta;
  let first = "";
  let last = "";
  let nrows = 0;
  for (let i = 0; i < rounds; i++) {
    const rows = tableRows(meta);
    first = rows[0];
    last = rows[rows.length - 1];
    nrows = rows.length;
  }
  console.log(`bench-table cs=${nrows}|${first}|${last}`);
  Deno.exit(0);
}

function cmdBenchLines(rest: string[]): never {
  const k = parseInt(benchArg(rest, "k", "20000"));
  let eta = 0;
  const samples: string[] = [];
  const step = Math.max(1, Math.floor(k / 40));
  for (let i = 0; i < k; i++) {
    const ln = progressLine(i);
    if (ln.includes("ETA")) eta += 1;
    if (i % step === 0) samples.push(ln.slice(12, 14));
  }
  console.log(`bench-lines cs=${eta},${samples.join(",")}`);
  Deno.exit(0);
}

function cmdBenchSpawn(rest: string[]): never {
  const n = parseInt(benchArg(rest, "n", "30"));
  let ok = 0;
  for (let i = 0; i < n; i++) {
    try {
      const cmd = new Deno.Command("mockspawn", { args: ["--version"], stdout: "piped", stderr: "piped" });
      const { code } = cmd.outputSync();
      if (code === 0) ok += 1;
    } catch (_e) {
      /* missing engine — counted as failure below */
    }
  }
  console.log(`bench-spawn cs=${ok}/${n}`);
  Deno.exit(ok === n ? 0 : 1);
}

function benchQueueWorker(chunk: number[]): number {
  let ok = 0;
  for (const _u of chunk) {
    try {
      const cmd = new Deno.Command("mocksleep", { args: ["80"], stdout: "piped", stderr: "piped" });
      const { code } = cmd.outputSync();
      if (code === 0) ok += 1;
    } catch (_e) {
      /* missing engine — counted as failure below */
    }
  }
  return ok;
}

async function cmdBenchQueue(rest: string[]): Promise<never> {
  const k = Math.max(1, parseInt(benchArg(rest, "k", "16")));
  const c = Math.min(Math.max(1, parseInt(benchArg(rest, "c", "8"))), k);
  const chunks: number[][] = Array.from({ length: c }, () => []);
  for (let i = 0; i < k; i++) chunks[i % c].push(i);
  let ok = 0;
  if (c === 1) {
    ok = benchQueueWorker(chunks[0]);
  } else {
    // run chunks concurrently: workers are synchronous sleeps, so the
    // honest way to overlap them here is worker threads — but to keep the
    // comparison shape identical to the queue path (event-loop tasks), we
    // spawn Deno.Command with async output and await all
    const ps = chunks.map((chunk) =>
      (async () => {
        let o = 0;
        for (const _u of chunk) {
          try {
            const cmd = new Deno.Command("mocksleep", { args: ["80"], stdout: "piped", stderr: "piped" });
            const { code } = await cmd.output();
            if (code === 0) o += 1;
          } catch (_e) {
            /* missing engine */
          }
        }
        return o;
      })(),
    );
    const oks = await Promise.all(ps);
    ok = oks.reduce((a, b) => a + b, 0);
  }
  console.log(`bench-queue cs=ok${ok},k${k},c${c}`);
  Deno.exit(ok === k ? 0 : 1);
}

function usage(): never {
  console.log("ytdl — YouTube downloader, Deno comparison build");
  console.log("");
  console.log("usage: deno run --allow-run --allow-read --allow-write ytdl.ts <cmd> [options]");
  console.log("cmds: doctor | info URL | get URL | queue FILE | selfcheck FIXTURE.json");
  console.log("options: --out DIR --quality N --format EXPR --audio KIND --subs");
  console.log("         --sub-langs LANGS --template T --jobs N --no-aria2");
  console.log("         --playlist --max-attempts N");
  console.log("bench (cross-language deep benchmark, docs/BENCHMARK-DEEP.md):");
  console.log("  bench-startup | bench-json F --n N | bench-table F --rounds R");
  console.log("  bench-lines --k K | bench-spawn --n N | bench-queue --k K --c C");
  Deno.exit(2);
}

// ---------------------------------------------------------- main

const a = [...Deno.args];
if (!a.length) usage();
const sub = a[0];
const rest = a.slice(1);
if (["help", "--help", "-h"].includes(sub)) {
  usage();
} else if (sub === "doctor") {
  await cmdDoctor();
} else if (sub === "info") {
  await cmdInfo(rest);
} else if (sub === "get") {
  await cmdGet(rest);
} else if (sub === "queue") {
  await cmdQueue(rest);
} else if (sub === "selfcheck") {
  await cmdSelfcheck(rest);
} else if (sub === "bench-startup") {
  cmdBenchStartup();
} else if (sub === "bench-json") {
  cmdBenchJson(rest);
} else if (sub === "bench-table") {
  cmdBenchTable(rest);
} else if (sub === "bench-lines") {
  cmdBenchLines(rest);
} else if (sub === "bench-spawn") {
  cmdBenchSpawn(rest);
} else if (sub === "bench-queue") {
  await cmdBenchQueue(rest);
} else {
  console.log(`error: unknown subcommand ${sub}`);
  usage();
}
