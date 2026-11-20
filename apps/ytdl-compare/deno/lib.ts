/**
 * lib.ts — shared core of the Deno/TypeScript ytdl comparison build.
 *
 * Split out of ytdl.ts (2026-11-21) to keep every file under the
 * complexity/file-too-large line limit (400): this module owns the pure
 * decision core — types, formatting, engine probes, selector logic, the
 * format table, the download loop and the option layer. The CLI commands,
 * the deep-bench workloads and the entry dispatch live in ytdl.ts, which
 * imports everything it needs from here.
 *
 * The decision logic must stay IDENTICAL to apps/ytdl/ytdl.op and the
 * Python build (differential-pinned): moving code between files must not
 * change any byte of printed output.
 */

export const TIERS = ["2160", "1440", "1080", "720", "480", "360", "240", "144"];
export const AUDIO_KINDS = ["mp3", "m4a", "opus", "flac", "wav"];
export const PARTIAL_SUFFIXES = [".part", ".ytdl", ".aria2", ".tmp"];

export interface RunResult {
  code: number;
  stdout: string;
  stderr: string;
}

export interface Opts {
  url: string;
  out: string;
  quality: string;
  audio: string;
  fmt: string;
  subs: boolean;
  sub_langs: string;
  jobs: number;
  aria2: boolean;
  playlist: boolean;
  template: string;
  max_attempts: number;
  aria2_ok: boolean;
}

export interface Fmt {
  format_id: string;
  ext: string;
  height?: number;
  width?: number;
  fps?: number;
  vcodec?: string;
  acodec?: string;
  tbr?: number;
  filesize?: number;
  filesize_approx?: number;
  format_note?: string;
}

export interface Meta {
  id?: string;
  title?: string;
  uploader?: string;
  duration?: number;
  view_count?: number;
  formats?: Fmt[];
}

// ---------------------------------------------------------- formatting

export function fmtBytes(n: number | undefined | null): string {
  if (n == null) return "?";
  const f = Number(n);
  if (f >= 1073741824.0) return `${(f / 1073741824.0).toFixed(2)} GB`;
  if (f >= 1048576.0) return `${(f / 1048576.0).toFixed(1)} MB`;
  if (f >= 1024.0) return `${(f / 1024.0).toFixed(1)} KB`;
  return `${n} B`;
}

export function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

export function fmtDur(s: number | undefined | null): string {
  if (s == null) return "?";
  const t = Math.floor(Number(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  if (h > 0) return `${h}:${pad2(m)}:${pad2(sec)}`;
  return `${m}:${pad2(sec)}`;
}

export function comma(n: number | undefined | null): string {
  if (n == null) return "?";
  return Math.floor(Number(n)).toLocaleString("en-US");
}

export function mget(m: Record<string, unknown> | Fmt | Meta, k: string): string {
  // Fmt/Meta lack index signatures, so the union is narrowed through one
  // cast at the single access point instead of at every call site
  const v = (m as Record<string, unknown>)[k];
  return v == null ? "" : String(v);
}

export function tailLines(s: string, n: number): string {
  const ls = s.trim().split("\n").filter((l) => l !== "");
  if (ls.length <= n) return ls.join("\n");
  return ls.slice(ls.length - n).join("\n");
}

// ---------------------------------------------------------- engines

export async function runProg(prog: string, args: string[], _timeoutMs = 300000): Promise<RunResult> {
  // _timeoutMs is kept for surface parity with the Python build (whose
  // run_prog enforces subprocess.run(timeout=...)); Deno.Command has no
  // per-call timeout in the pinned comparison shape, so the deadline is
  // the caller's concern here. Underscore-prefixed: deliberately unused.
  try {
    const cmd = new Deno.Command(prog, { args, stdout: "piped", stderr: "piped" });
    const { code, stdout, stderr } = await cmd.output();
    return {
      code,
      stdout: new TextDecoder().decode(stdout),
      stderr: new TextDecoder().decode(stderr),
    };
  } catch (_e) {
    throw new Error(`run denied — '${prog}' not found or not granted`);
  }
}

export async function toolLine(prog: string, flag: string): Promise<string> {
  try {
    const r = await runProg(prog, [flag], 30000);
    if (r.code === 0) return r.stdout.trim().split("\n")[0];
  } catch (_e) {
    /* not granted / not installed */
  }
  return "";
}

export async function detectTools() {
  return {
    ytdlp: await toolLine("yt-dlp", "--version"),
    ffmpeg: await toolLine("ffmpeg", "-version"),
    aria2: await toolLine("aria2c", "--version"),
  };
}

// ---------------------------------------------------------- selection logic
// must stay IDENTICAL to apps/ytdl/ytdl.op (differential-pinned)

export function qualityExpr(q: string): string {
  if (q === "best") return "bestvideo*+bestaudio/best";
  return `bestvideo[height<=${q}]+bestaudio/best[height<=${q}]/best`;
}

export function selectionArgs(o: Partial<Opts>): string[] {
  if (o.fmt) return ["-f", o.fmt];
  if (o.audio) {
    return ["-f", "bestaudio/best", "-x", "--audio-format", o.audio, "--audio-quality", "0"];
  }
  return ["-f", qualityExpr(o.quality ?? "best")];
}

export function buildGetArgs(url: string, o: Opts): string[] {
  const a: string[] = [];
  if (!o.playlist) a.push("--no-playlist");
  a.push("--continue", "--retries", "3", "--fragment-retries", "3", "--no-overwrites");
  if (o.aria2 && o.aria2_ok) {
    a.push("--downloader", "aria2c", "--downloader-args", "aria2c:-x16 -s16 -k1M --file-allocation=none");
  }
  if (o.subs) {
    a.push("--write-subs", "--sub-langs", o.sub_langs, "--convert-subs", "srt");
  }
  a.push("-P", o.out, "-o", o.template);
  a.push(...selectionArgs(o));
  a.push(url);
  return a;
}

// ---------------------------------------------------------- format table

export function hOf(f: Fmt): number {
  return f.height == null ? 0 : f.height;
}

export function tOf(f: Fmt): number {
  return f.tbr == null ? 0 : f.tbr;
}

export function resOf(f: Fmt): string {
  const h = hOf(f);
  if (h <= 0) return mget(f, "vcodec") === "none" ? "audio" : "?";
  const w = f.width ?? 0;
  return w > 0 ? `${w}x${h}` : `?x${h}`;
}

export function sizeOf(f: Fmt): string {
  if (f.filesize != null) return fmtBytes(f.filesize);
  if (f.filesize_approx != null) return `~${fmtBytes(f.filesize_approx)}`;
  return "?";
}

export function clip(s: string, w: number): string {
  return s.length > w ? s.slice(0, w - 2) + ".." : s;
}

export function fmtRow(f: Fmt): string {
  const fps = f.fps != null ? String(Math.floor(f.fps)) : "";
  let vc = mget(f, "vcodec") || "?";
  if (vc === "none") vc = "-";
  let ac = mget(f, "acodec") || "?";
  if (ac === "none") ac = "-";
  const p = (s: string, w: number, dir: "l" | "r") =>
    dir === "l" ? clip(s, w).padEnd(w) : clip(s, w).padStart(w);
  return (
    p(mget(f, "format_id"), 9, "l") + "  " +
    p(mget(f, "ext"), 4, "l") + "  " +
    p(resOf(f), 10, "l") + "  " +
    p(fps, 4, "r") + "  " +
    p(sizeOf(f), 9, "r") + "  " +
    p(`${vc}/${ac}`, 19, "l") + "  " +
    mget(f, "format_note")
  );
}

export function tableRows(meta: Meta): string[] {
  // pure decision pipeline: sort + row-build, NO engine probes — the
  // workload the deep benchmark times in every language build
  const out: string[] = [];
  out.push(`title: ${mget(meta, "title")}`);
  out.push(
    `by: ${mget(meta, "uploader")}  |  duration: ${fmtDur(meta.duration)}  |  views: ${comma(meta.view_count)}`,
  );
  const n = meta.formats ? meta.formats.length : 0;
  out.push(`formats: ${n}  (res = WxH, size from yt-dlp, ~ = approximate)`);
  out.push("id        ext   res         fps      size  vcodec/acodec        note");
  const fs = (meta.formats ?? []).slice().sort((a, b) => {
    if (hOf(a) > hOf(b)) return -1;
    if (hOf(a) < hOf(b)) return 1;
    return tOf(a) > tOf(b) ? -1 : 1;
  });
  for (const f of fs) out.push(fmtRow(f));
  return out;
}

export function infoLines(meta: Meta): string[] {
  const out = tableRows(meta);
  const tools = detectToolsSync();
  if (tools.aria2) {
    out.push(`accel: aria2c ${tools.aria2} (multi-connection enabled)`);
  } else {
    out.push("accel: aria2c not found — single-connection downloads");
  }
  return out;
}

export function detectToolsSync() {
  // shell-out probe kept synchronous so table paths stay simple
  const line = (prog: string, flag: string): string => {
    try {
      const cmd = new Deno.Command(prog, { args: [flag], stdout: "piped", stderr: "piped" });
      const { code, stdout } = cmd.outputSync();
      if (code === 0) return new TextDecoder().decode(stdout).trim().split("\n")[0];
    } catch (_e) {
      /* not granted / not installed */
    }
    return "";
  };
  return {
    ytdlp: line("yt-dlp", "--version"),
    ffmpeg: line("ffmpeg", "-version"),
    aria2: line("aria2c", "--version"),
  };
}

// ---------------------------------------------------------- download

export function hasPartial(d: string): boolean {
  try {
    for (const name of Deno.readDirSync(d)) {
      if (PARTIAL_SUFFIXES.some((s) => name.name.endsWith(s))) return true;
    }
  } catch (_e) {
    return false;
  }
  return false;
}

export function destLines(stdout: string, stderr: string): string[] {
  const found: string[] = [];
  for (const src of [stdout, stderr]) {
    for (const raw of src.split("\n")) {
      const l = raw.trim();
      if (
        l.includes("Destination:") || l.includes("has already been downloaded") ||
        l.includes("[Merger]") || l.includes("Download complete:") || l.includes("ExtractAudio")
      ) {
        found.push(l);
      }
    }
  }
  return found;
}

export async function download(url: string, o: Opts) {
  let attempts = 0;
  let last: RunResult = { code: -1, stdout: "", stderr: "" };
  while (true) {
    attempts += 1;
    last = await runProg("yt-dlp", buildGetArgs(url, o));
    if (last.code === 0 && !hasPartial(o.out)) break;
    if (attempts >= o.max_attempts) break;
  }
  const ok = last.code === 0 && !hasPartial(o.out);
  return { ok, attempts, r: last };
}

export function report(d: { ok: boolean; attempts: number; r: RunResult }) {
  for (const ln of destLines(d.r.stdout, d.r.stderr)) console.log(`  ${ln}`);
  console.log(`  attempts: ${d.attempts}  result: ${d.ok ? "ok" : "FAIL"}`);
  if (!d.ok) {
    console.log(d.r.code !== 0 ? `  yt-dlp exited ${d.r.code}:` : `  incomplete after ${d.attempts} rounds:`);
    console.log(tailLines(d.r.stderr, 4));
  }
}

// ---------------------------------------------------------- option layer

export function getOpts(rest: string[]): Opts {
  function val(name: string, def: string): string {
    const f = `--${name}`;
    for (let i = 0; i < rest.length; i++) {
      if (rest[i] === f) return i + 1 < rest.length ? rest[i + 1] : def;
      if (rest[i].startsWith(f + "=")) return rest[i].slice(f.length + 1);
    }
    return def;
  }
  const flag = (name: string) => rest.includes(`--${name}`);
  const pos: string[] = [];
  let i = 0;
  while (i < rest.length) {
    const a = rest[i];
    if (a.startsWith("--")) i += a.includes("=") ? 1 : 2;
    else if (a.startsWith("-")) i += 1;
    else {
      pos.push(a);
      i += 1;
    }
  }
  const o: Opts = {
    url: pos[0] ?? "",
    out: val("out", "downloads"),
    quality: val("quality", "best"),
    audio: val("audio", ""),
    fmt: val("format", ""),
    subs: flag("subs"),
    sub_langs: val("sub-langs", "en"),
    jobs: parseInt(val("jobs", "2")),
    aria2: !flag("no-aria2"),
    playlist: flag("playlist"),
    template: val("template", "%(title)s [%(id)s].%(ext)s"),
    max_attempts: parseInt(val("max-attempts", "4")),
    aria2_ok: false,
  };
  o.aria2_ok = false; // set async in main before get/queue use it
  return o;
}

export function die(msg: string, code = 2): never {
  console.log(msg);
  Deno.exit(code);
}
