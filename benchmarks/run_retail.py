"""Run a small Retail evaluation using the official tau2 runner (real API calls)."""

import argparse
import json
import os
from pathlib import Path

from backend import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-tasks", type=int, default=2)
    parser.add_argument(
        "--all", action="store_true", help="Run every registered English Retail base task"
    )
    parser.add_argument("--task-ids", nargs="+", default=None)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--user-model", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--save-to", default="deep-retail")
    args = parser.parse_args()
    if config.MODE != "live" or not config.API_KEY:
        parser.error(
            "评测需要 AGENT_MODE=live 和 MODEL_API_KEY，演示模式不提供有效 benchmark 分数。"
        )
    # The official user simulator uses LiteLLM, independent from the agent's ChatOpenAI.
    os.environ.setdefault("OPENAI_API_KEY", config.API_KEY)
    if config.BASE_URL:
        os.environ.setdefault("OPENAI_API_BASE", config.BASE_URL)
    from tau2.data_model.semantic_communication import (
        CommunicateScoring,
        SemanticCommunicateSettings,
    )
    from tau2.data_model.simulation import TextRunConfig
    from tau2.evaluator import evaluator_nl_assertions
    from tau2.registry import registry
    from tau2.runner import run_domain

    from benchmarks.tau2_agent import factory

    registry.register_agent_factory(factory, "deep_retail")
    user_model = args.user_model or (
        f"openai/{config.MODEL}" if config.IS_DEEPSEEK else "openai/gpt-4.1-mini"
    )
    judge_model = args.judge_model or user_model
    provider_args = {"temperature": 0}
    if config.BASE_URL:
        provider_args["api_base"] = config.BASE_URL
    if config.IS_DEEPSEEK:
        provider_args["extra_body"] = {"thinking": {"type": "disabled"}}
    # Explicit local judge override, leaving the upstream files and task criteria intact.
    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS = judge_model
    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS = provider_args
    result = run_domain(
        TextRunConfig(
            domain="retail",
            agent="deep_retail",
            user="user_simulator",
            llm_agent=config.MODEL,
            llm_user=user_model,
            llm_args_user=provider_args,
            communicate_scoring=CommunicateScoring(
                judge=SemanticCommunicateSettings(model=judge_model, model_args=provider_args)
            ),
            num_tasks=None if args.all or args.task_ids else args.num_tasks,
            task_ids=args.task_ids,
            num_trials=1,
            max_concurrency=args.concurrency,
            max_steps=args.max_steps,
            timeout=args.timeout,
            seed=args.seed,
            max_retries=0,
            auto_review=False,
            hallucination_retries=0,
            save_to=args.save_to,
        )
    )
    output = config.ROOT / "runtime/benchmarks"
    output.mkdir(parents=True, exist_ok=True)
    slug = Path(args.save_to).name
    (output / f"{slug}.json").write_text(result.model_dump_json(indent=2))
    print(
        json.dumps(
            {
                "saved_result": str(output / f"{slug}.json"),
                "agent_model": config.MODEL,
                "user_model": user_model,
                "judge_model": judge_model,
                "seed": args.seed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
