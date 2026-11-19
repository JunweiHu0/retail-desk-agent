# 课程原始 serve.sh（集群实测抓取，2026-11-18）

来自 `retail-serve-inspect` 作业 29495，`cat "$QWEN_PROJECT_ROOT/serve.sh"` 的原文。
我们部署的 `deploy/tacc/serve/job.sh` 在此基础上增加了工具调用两个参数和端口扫描，其余一致。

```bash
#!/usr/bin/env bash
set -euo pipefail
project=/mnt/home/public/course-envs/CSIT6000V/project/qwen3.8-27b-v1
: "${QWEN_RUN_DIR:?First source the public project/activate.sh}"
export CUDA_VISIBLE_DEVICES=0,1
exec bash "$project/runtime.sh" "$project/vllm-env/bin/python" \
    -m vllm.entrypoints.openai.api_server \
    --model "$project/models/Qwen3.8-27B-AWQ-INT4" \
    --served-model-name qwen3.8-27b \
    --safetensors-load-strategy prefetch \
    --host 0.0.0.0 --port 8000 \
    --tensor-parallel-size 2 --language-model-only --dtype bfloat16 \
    --gpu-memory-utilization 0.90 --max-model-len 32768 \
    --max-num-seqs 4 --max-num-batched-tokens 4096 \
    --reasoning-parser qwen3 --enable-prefix-caching
```

要点：

- **`--tensor-parallel-size 2`**：课程默认就是双卡张量并行
- 没有开 tool calling：这是示例服务，客户端只做普通对话
- `--enable-prefix-caching` 默认开；`--reasoning-parser qwen3` 默认开
