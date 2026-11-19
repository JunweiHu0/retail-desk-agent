"""Sample vLLM /metrics every 2 s into JSONL, for window-delta analysis.

The engine only exposes counters and coarse histograms; TPOT and cache-hit
rate are interval quantities, so one scrape cannot produce them. Run this
while a load or an evaluation is in flight, then diff consecutive samples.

  ssh -f -N -L 127.0.0.1:8002:<serve-node>:8000 <you>@<gateway>
  python3 deploy/tacc/bench/sampler.py --url http://127.0.0.1:8002/metrics --out /tmp/kvlog.jsonl
"""
import argparse, json, re, time, urllib.request
ap = argparse.ArgumentParser()
ap.add_argument('--url', default='http://127.0.0.1:8002/metrics')
ap.add_argument('--out', default='/tmp/vllm-metrics.jsonl')
ap.add_argument('--interval', type=float, default=2.0)
ARGS = ap.parse_args()
line_re = re.compile(r'(vllm:[a-z0-9_]+)\{(.*)\}\s+([0-9.eE+-]+)')
with open(ARGS.out,'a') as out:
    while True:
        try:
            text = urllib.request.urlopen(ARGS.url, timeout=5).read().decode()
            v = {}
            for l in text.splitlines():
                m = line_re.match(l)
                if m:
                    v[m.group(1)] = v.get(m.group(1), 0.0) + float(m.group(3))
            out.write(json.dumps({'t': round(time.time(),2),
                'running': v.get('vllm:num_requests_running',0),
                'waiting': v.get('vllm:num_requests_waiting',0),
                'kv': round(v.get('vllm:kv_cache_usage_perc',0),4),
                'prompt': v.get('vllm:prompt_tokens_total',0),
                'gen': v.get('vllm:generation_tokens_total',0),
                'reqs': v.get('vllm:request_success_total',0),
                'preempt': v.get('vllm:num_preemptions_total',0),
                'hits': v.get('vllm:prefix_cache_hits_total',0),
                'queries': v.get('vllm:prefix_cache_queries_total',0),
                'ttft_sum': v.get('vllm:time_to_first_token_seconds_sum',0),
                'ttft_n': v.get('vllm:time_to_first_token_seconds_count',0),
                'e2e_sum': v.get('vllm:e2e_request_latency_seconds_sum',0),
                'e2e_n': v.get('vllm:e2e_request_latency_seconds_count',0)})+'\n')
            out.flush()
        except Exception:
            pass
        time.sleep(ARGS.interval)
