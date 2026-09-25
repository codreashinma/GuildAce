"""Escrow の配分計算。AI は関与しない。
配分 = Human Task の worker に各報酬、残額（PM 手数料 + AI タスク分）は PM Agent の受取アドレス。"""

from ..models import Case


def compute_split(case: Case) -> list[dict]:
    budget = int(case.budget)
    per_address: dict[str, int] = {}
    labels: dict[str, str] = {}
    human_total = 0
    for t in case.tasks:
        if t.type == "human" and t.human_task and t.human_task.worker and t.human_task.status == "done":
            addr = t.human_task.worker.wallet_address
            amt = int(t.human_task.reward)
            per_address[addr] = per_address.get(addr, 0) + amt
            labels[addr] = "Human Task worker"
            human_total += amt
    agent_addr = case.agent.payout_address.lower()
    per_address[agent_addr] = per_address.get(agent_addr, 0) + (budget - human_total)
    labels[agent_addr] = f"PM Agent {case.agent.name}"
    return [
        {"address": a, "amount": str(v), "label": labels[a]}
        for a, v in per_address.items()
        if v > 0
    ]


def refund_split(case: Case) -> list[dict]:
    return [{"address": case.client.wallet_address, "amount": str(int(case.budget)), "label": "発注者への返金"}]
