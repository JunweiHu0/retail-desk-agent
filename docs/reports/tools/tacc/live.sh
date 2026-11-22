# usage: live.sh variant jobid  -> prints key progress lines of a running job
TC=/home/mnyh/.local/bin/tcloud
timeout 200 $TC cat slurm_log/retail-p3-$1-$2.log 2>/dev/null | tr -d '\r' | grep -a -v -i -E "api_key|password|secret" \
 | grep -a -E "RESUME_|RETAIL_|Status: |Traceback|Error:|error:" | grep -av "isn't mapped" | tail -4 | cut -c1-220
