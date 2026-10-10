/**
 * Run a batch of masked image edits against OpenAI's /v1/images/edits.
 *
 *   node scripts/avatar2d/generate.mjs <jobs.json>
 *
 * jobs.json: { "log": "<dir>/api-log.jsonl", "jobs": [
 *   { "out": "<png>", "input": "<png>", "mask": "<png>"?, "prompt": "...",
 *     "model": "gpt-image-2.5-sunburst", "n": 1, "background": "opaque"? } ] }
 *
 * Jobs whose output already exists are skipped, so a batch can be re-run after
 * a failure. The org limit is 20 input images per minute per model family
 * (image and mask both count); a sliding-window limiter keeps under it, and a
 * 429 backs off and retries. OPENAI_API_KEY comes from the environment only.
 */
import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync } from 'node:fs';
import { basename, dirname } from 'node:path';

const LIMIT_PER_MIN = 18;          // a little under the org's 20
const WINDOW_MS = 61_000;
const CONCURRENCY = 4;

const key = process.env.OPENAI_API_KEY;
if (!key) { console.error('OPENAI_API_KEY is not set'); process.exit(2); }

const spec = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const family = (m) => m.replace(/-(sunburst|flare).*$/, '');
const sent = {};                   // family -> timestamps of input images

async function reserve(model, count) {
    const f = family(model);
    sent[f] ||= [];
    for (;;) {
        const now = Date.now();
        sent[f] = sent[f].filter((t) => now - t < WINDOW_MS);
        if (sent[f].length + count <= LIMIT_PER_MIN) {
            for (let i = 0; i < count; i++) sent[f].push(now);
            return;
        }
        await new Promise((r) => setTimeout(r, Math.max(500, WINDOW_MS - (now - sent[f][0]))));
    }
}

function outName(out, i, n) {
    return n > 1 ? out.replace(/\.png$/, `_${i}.png`) : out;
}

async function run(job) {
    const n = job.n || 1;
    if (existsSync(outName(job.out, 0, n))) return `skip ${basename(job.out)}`;
    mkdirSync(dirname(job.out), { recursive: true });
    const model = job.model || 'gpt-image-2.5-sunburst';
    const inputs = 1 + (job.mask ? 1 : 0);
    for (let attempt = 0; attempt < 4; attempt++) {
        await reserve(model, inputs);
        const fd = new FormData();
        fd.append('model', model);
        fd.append('prompt', job.prompt);
        fd.append('size', job.size || '1024x1536');
        fd.append('quality', job.quality || 'high');
        if (job.background) fd.append('background', job.background);
        fd.append('n', String(n));
        fd.append('image', new Blob([readFileSync(job.input)], { type: 'image/png' }), basename(job.input));
        if (job.mask) fd.append('mask', new Blob([readFileSync(job.mask)], { type: 'image/png' }), basename(job.mask));
        const t0 = Date.now();
        const res = await fetch('https://api.openai.com/v1/images/edits', {
            method: 'POST', headers: { Authorization: `Bearer ${key}` }, body: fd,
        });
        const j = await res.json().catch(() => ({}));
        appendFileSync(spec.log, JSON.stringify({
            at: new Date().toISOString(), model, out: job.out, status: res.status, ms: Date.now() - t0,
            inputs, n, error: j.error?.message,
        }) + '\n');
        if (res.status === 429) {
            await new Promise((r) => setTimeout(r, 30_000 * (attempt + 1)));
            continue;
        }
        if (!res.ok) return `FAIL ${basename(job.out)}: ${res.status} ${j.error?.message?.slice(0, 120)}`;
        (j.data || []).forEach((d, i) => writeFileSync(outName(job.out, i, n), Buffer.from(d.b64_json, 'base64')));
        return `ok ${basename(job.out)} (${Date.now() - t0}ms)`;
    }
    return `FAIL ${basename(job.out)}: rate limited`;
}

const queue = [...spec.jobs];
const results = [];
await Promise.all(Array.from({ length: CONCURRENCY }, async () => {
    while (queue.length) {
        const job = queue.shift();
        const r = await run(job).catch((e) => `FAIL ${basename(job.out)}: ${e.message}`);
        console.log(r);
        results.push(r);
    }
}));
const failed = results.filter((r) => r.startsWith('FAIL')).length;
console.log(`${results.length} jobs, ${failed} failed`);
process.exit(failed ? 1 : 0);
