# 2026-11-18 · prefill 干扰测试：该不该做 PD 分离

一次请求在稳定解码；中途打进去一个 5,000 token 的长 prefill，看前者会不会被拖慢。
5 次试验，每次 384 token 输出。

| 项 | 值 |
| --- | --- |
| serve / bench 作业 | 29483 / 29487 |
| 节点 | 10-0-4-11（serve），10-0-1-11（bench） |
| serve 配置 | TP=2，max-num-seqs 4，chunked prefill 4096，prefix caching |
| 注入时机 | 解码出 20 个 token 之后 |

## 结果

```
基线 TPOT（prefill 之前）   15.25 ms
prefill 期间 TPOT 中位数    15.29 ms   (×1.00)
最差单次 token 间隔         514.8 ms
```

| 试验 | prefill 前 | prefill 期间 | 最差间隔 |
| --- | --- | --- | --- |
| 0 | 15.35 | 15.28 | 513.0 |
| 1 | 15.25 | 15.26 | 514.2 |
| 2 | 15.22 | 15.29 | 511.3 |
| 3 | 15.20 | 15.29 | 512.1 |
| 4 | 15.22 | 15.32 | 514.8 |

## 结论

1. **中位 TPOT 完全不动**（×1.00）：prefill 不会持续拖慢解码。
2. **但有一次约 0.5 秒的停顿**：长 prefill 被调度进来的那一个 step，解码等了一个 chunk。
3. **在并发 1 的真实负载里，这个重叠根本不会发生**——prefill 和 decode 是串行的。
   所以对本项目，PD 分离没有收益。
4. 只有并发 ≥2 时，每个新请求会让其他请求的一个 token 卡 0.5 s，PD 才有意义。

这条结论比"PD 不适用"硬：有测量、有边界条件、有量化。

## 复现

```bash
BENCH_SCRIPT=interference.py ./deploy/run.sh tacc bench
```

文件：`interference.json`（5 次试验的逐项数字）。
