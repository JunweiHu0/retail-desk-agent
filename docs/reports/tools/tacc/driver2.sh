#!/bin/bash
# Chain 1-hour TACC slices for the p3 runs. Only touches junwei's own jobs.
# usage: driver2.sh "bare:ID generic:ID probe:ID deep:ID"
# Fixes over driver.sh:
#  - an empty queue (no junwei jobs) is a valid state, not "unknown"
#  - only a failed `tcloud ps` (non-zero exit or no header) counts as unknown
#  - a slice that ended abnormally but made progress is resubmitted (fail count reset)
#  - TRIALS=1 -> FINAL_TRIALS promotion (trial 0 first for the baselines)
#  - rubric job submitted once bare and generic trial 0 are complete
TC=/home/mnyh/.local/bin/tcloud
B=/home/mnyh/projects/retail-agent/runtime/tacc-eval-20261122-proposal
OUT=/home/mnyh/eval-dl/p3; mkdir -p $OUT
LOG=$OUT/driver.log
declare -A JOB PREV FAILS SUBS DONE
for kv in $1; do v=${kv%%:*}; JOB[$v]=${kv##*:}; PREV[$v]=-1; FAILS[$v]=0; SUBS[$v]=1; DONE[$v]=""; done
RUBRIC_SENT=""
say(){ echo "$(date '+%F %T') $*" | tee -a $LOG; }
queue(){ # prints junwei rows; returns 1 if the queue could not be read
  local all; all=$(timeout 120 $TC ps 2>/dev/null | tr -d '\r') || return 1
  echo "$all" | grep -aq "JOBID" || return 1
  echo "$all" | grep -a junwei
  return 0
}
submit(){ # $1 variant -> echoes new job id
  cd $B/retail-p3-$1 || return 1
  local before after
  before=$(queue | awk '{print $1}' | sort)
  timeout 300 $TC submit >/dev/null 2>&1
  sleep 20
  after=$(queue | awk '{print $1}' | sort)
  comm -13 <(echo "$before") <(echo "$after") | tail -1
}
envget(){ grep -a "^$2=" $B/retail-p3-$1/variant.env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '"'; }
say "driver2 start ${!JOB[*]} -> ${JOB[*]}"
while :; do
  alldone=1
  if ! q=$(queue); then say "queue unreadable, retry"; sleep 300; continue; fi
  for v in "${!JOB[@]}"; do
    [[ -n "${DONE[$v]}" ]] && continue
    alldone=0
    id=${JOB[$v]}
    if echo "$q" | awk '{print $1}' | grep -qx "$id"; then continue; fi
    # job left the queue: read its log (download to temp, keep a filtered copy)
    tmp=$OUT/$v-$id.log.tmp
    timeout 300 $TC cat slurm_log/retail-p3-$v-$id.log > $tmp 2>/dev/null
    grep -a -v -i -E "api_key|token|password|secret" $tmp > $OUT/$v-$id.log; rm -f $tmp
    last=$(grep -a -o "RESUME_CHECKPOINT scored=[0-9]*/[0-9]*" $OUT/$v-$id.log | tail -1 | sed -E 's/.*scored=([0-9]+)\/.*/\1/')
    last=${last:-${PREV[$v]}}
    if grep -aq -E "RETAIL_EVAL_COMPLETE|STREAM_PROBE_COMPLETE|RUBRIC_COMPLETE" $OUT/$v-$id.log; then
      tr=$(envget $v TRIALS); ft=$(envget $v FINAL_TRIALS)
      if [[ -n "$ft" && -n "$tr" && "$ft" -gt "$tr" ]]; then
        sed -i "s/^TRIALS=.*/TRIALS=\"$ft\"/" $B/retail-p3-$v/variant.env
        say "$v job $id trial-0 phase COMPLETE scored=$last -> TRIALS=$ft"
        touch $OUT/$v.phase1.done
      else
        DONE[$v]=complete; say "$v job $id COMPLETE scored=$last"; continue
      fi
    elif grep -aq RETAIL_EVAL_NEXT_SLICE $OUT/$v-$id.log; then
      FAILS[$v]=0
      if (( last <= PREV[$v] )); then DONE[$v]=stalled; say "$v job $id no progress (scored=$last) -> STALLED"; continue; fi
    else
      if (( last > PREV[$v] && PREV[$v] >= 0 )); then FAILS[$v]=0; else FAILS[$v]=$((FAILS[$v]+1)); fi
      say "$v job $id ended abnormally (fail ${FAILS[$v]}, lines=$(wc -l < $OUT/$v-$id.log)): $(grep -a -E 'RESUME_|Error|error' $OUT/$v-$id.log | grep -av "isn't mapped" | tail -3 | tr '\n' '|' | cut -c1-300)"
      if (( FAILS[$v] >= 2 )); then DONE[$v]=failed; say "$v STOP after repeated failures"; continue; fi
    fi
    PREV[$v]=$last
    if (( SUBS[$v] >= 25 )); then DONE[$v]=maxslices; say "$v STOP max slices"; continue; fi
    nid=$(submit $v)
    if [[ -z "$nid" ]]; then say "$v resubmit failed"; DONE[$v]=submitfail; continue; fi
    JOB[$v]=$nid; SUBS[$v]=$((SUBS[$v]+1)); say "$v job $id scored=$last -> submitted $nid (slice ${SUBS[$v]})"
  done
  if [[ -z "$RUBRIC_SENT" && -e $OUT/bare.phase1.done && -e $OUT/generic.phase1.done ]]; then
    nid=$(submit rubric); RUBRIC_SENT=1
    if [[ -n "$nid" ]]; then JOB[rubric]=$nid; PREV[rubric]=-1; FAILS[rubric]=0; SUBS[rubric]=1; DONE[rubric]=""; alldone=0; say "rubric submitted $nid"
    else say "rubric submit failed"; fi
  fi
  (( alldone )) && break
  sleep 300
done
say "driver2 end: $(for v in "${!DONE[@]}"; do echo -n "$v=${DONE[$v]} "; done)"
