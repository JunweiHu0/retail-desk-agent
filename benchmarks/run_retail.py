"""Run a small Retail evaluation using the official tau2 runner (real API calls)."""

import argparse
import os

from backend import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-tasks", type=int, default=2)
    parser.add_argument("--user-model", default="openai/gpt-4.1-mini")
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
    from tau2.data_model.simulation import TextRunConfig
    from tau2.registry import registry
    from tau2.runner import run_domain

    from benchmarks.tau2_agent import factory

    registry.register_agent_factory(factory, "deep_retail")
    result = run_domain(
        TextRunConfig(
            domain="retail",
            agent="deep_retail",
            user="user_simulator",
            llm_agent=config.MODEL,
            llm_user=args.user_model,
            num_tasks=args.num_tasks,
            num_trials=1,
            max_concurrency=1,
            save_to=args.save_to,
        )
    )
    print(result)


if __name__ == "__main__":
    main()
