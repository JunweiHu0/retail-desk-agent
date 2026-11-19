"""Run a Retail evaluation using the official tau2 runner (real model calls).

  python -m benchmarks.run_retail --agent bare --task-ids 0,1
  python -m benchmarks.run_retail --agent deep_retail --num-tasks 10

`bare` is the no-tool control: same model and policy, no tools, so it should
score near zero on tasks that need an action. It exists to be the floor of the
quality comparison and to exercise the runner without the tool layer.
"""

import argparse
import os

from backend import config

AGENTS = {"deep_retail": "deep_retail", "bare": "bare_llm"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=sorted(AGENTS), default="deep_retail")
    parser.add_argument("--task-ids", default="", help="comma separated; overrides --num-tasks")
    parser.add_argument("--split", default="base")
    parser.add_argument("--num-tasks", type=int, default=2)
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--user-model", default="openai/gpt-4.1-mini")
    parser.add_argument("--save-to", default="deep-retail")
    parser.add_argument("--no-auto-resume", action="store_true",
                        help="by default a rerun resumes the checkpoint in --save-to")
    args = parser.parse_args()

    if config.MODE != "live" or not config.API_KEY:
        parser.error(
            "评测需要 AGENT_MODE=live 和 MODEL_API_KEY，演示模式不提供有效 benchmark 分数。"
        )
    # The official user simulator uses LiteLLM, independent from the agent's ChatOpenAI.
    os.environ.setdefault("OPENAI_API_KEY", config.API_KEY)
    if config.BASE_URL:
        # LiteLLM reads the legacy name; the OpenAI SDK reads the other one.
        os.environ.setdefault("OPENAI_API_BASE", config.BASE_URL)
        os.environ.setdefault("OPENAI_BASE_URL", config.BASE_URL)

    # tau2 scores NL assertions with a hardcoded judge model that this endpoint
    # does not serve; point it at our model instead of failing the whole task.
    from tau2.evaluator import evaluator_nl_assertions as nl_eval

    nl_eval.DEFAULT_LLM_NL_ASSERTIONS = f"openai/{config.MODEL}"
    nl_eval.DEFAULT_LLM_NL_ASSERTIONS_ARGS = {}

    from tau2.data_model.simulation import TextRunConfig
    from tau2.registry import registry
    from tau2.runner import run_domain

    from benchmarks import tau2_agent

    registry.register_agent_factory(tau2_agent.factory, "deep_retail")
    registry.register_agent_factory(tau2_agent.no_tool_factory, "bare_llm")

    ids = [item.strip() for item in args.task_ids.split(",") if item.strip()]
    print(f"agent={args.agent} split={args.split} task_ids={ids or '-'} "
          f"num_tasks={None if ids else args.num_tasks} trials={args.num_trials} "
          f"user_model={args.user_model} save_to={args.save_to}")

    result = run_domain(
        TextRunConfig(
            domain="retail",
            agent=AGENTS[args.agent],
            user="user_simulator",
            llm_agent=config.MODEL,
            llm_user=args.user_model,
            task_split_name=args.split,
            task_ids=ids or None,
            num_tasks=None if ids else args.num_tasks,
            num_trials=args.num_trials,
            max_concurrency=args.max_concurrency,
            seed=args.seed,
            save_to=args.save_to,
            auto_resume=not args.no_auto_resume,
        )
    )
    print(result)


if __name__ == "__main__":
    main()
