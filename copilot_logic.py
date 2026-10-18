"""Money Copilot: QVAC answers freely and uses tools to look at the student's data.

No scripted topics or canned answers. QVAC decides which tools to call
(budget, category statistics, transactions, calculator) and writes the answer.
Python only executes the tools and shows what they returned.

answer_question() returns {"text": str, "caption": str}.
"""
import ast
import json
import operator

from qvac_client import run_agent

try:
    from rgb_client import get_stusd_balance
except Exception:  # RGB client is optional: the copilot still works without it
    get_stusd_balance = None

TOOLS = [
    {
        "name": "get_budget",
        "description": "Get the student's balance, upcoming expenses, reserved total and "
                       "safe-to-spend amount (all in EUR).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_category_stats",
        "description": "Past spending statistics for one category: number of transactions, "
                       "total and average per transaction.",
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "A known category name"}},
            "required": ["category"],
        },
    },
    {
        "name": "list_transactions",
        "description": "List recent past transactions, optionally only for one category.",
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "Optional category name"}},
        },
    },
    {
        "name": "get_rgb_wallet_balance",
        "description": "Get the student's live RGB wallet balance in STUSD (settled, future and "
                       "spendable). Use this for any question about the STUSD or RGB wallet. "
                       "STUSD is separate from the EUR budget; there is no exchange rate.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "calculate",
        "description": "Evaluate an arithmetic expression such as 5*30.95 or 189-154.75. "
                       "Always use this for any math.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
]

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Only + - * / and numbers are allowed.")


def calculate(expression: str) -> float:
    cleaned = str(expression).replace("€", "").replace(",", "").strip()
    return round(float(_eval(ast.parse(cleaned, mode="eval"))), 2)


def _toolkit(summary: dict, expenses: list, transactions: list):
    categories = sorted({str(t.get("category", "Other")) for t in transactions})

    def match(name):
        wanted = str(name or "").strip().lower()
        for c in categories:
            if c.lower() == wanted:
                return c
        for c in categories:
            if wanted and (wanted in c.lower() or c.lower() in wanted):
                return c
        return None

    def execute(name: str, args: dict):
        if name == "get_budget":
            return {
                "balance": round(float(summary["balance"]), 2),
                "reserved_total": round(float(summary["mandatory_expenses"]), 2),
                "safe_to_spend": round(float(summary["safe_to_spend"]), 2),
                "upcoming_expenses": [
                    {"name": e["name"], "amount": float(e["amount"]), "due": e["due_date"]}
                    for e in expenses
                ],
            }
        if name == "get_category_stats":
            category = match(args.get("category"))
            if category is None:
                return {"error": f"Unknown category. Known categories: {', '.join(categories)}"}
            amounts = [float(t["amount"]) for t in transactions
                       if t.get("category") == category and float(t["amount"]) > 0]
            return {
                "category": category,
                "transactions": len(amounts),
                "total": round(sum(amounts), 2),
                "average": round(sum(amounts) / len(amounts), 2),
            }
        if name == "list_transactions":
            category = match(args.get("category")) if args.get("category") else None
            rows = [t for t in transactions if category is None or t.get("category") == category]
            rows = sorted(rows, key=lambda t: str(t.get("date", "")), reverse=True)[:20]
            return [
                {"date": t["date"], "merchant": t.get("merchant"),
                 "category": t.get("category"), "amount": float(t["amount"])}
                for t in rows
            ]
        if name == "get_rgb_wallet_balance":
            if get_stusd_balance is None:
                return {"error": "The RGB client is not available."}
            data = get_stusd_balance()
            return {
                "unit": "STUSD",
                "settled": int(data.get("settled", 0)),
                "future": int(data.get("future", 0)),
                "spendable": int(data.get("spendable", 0)),
            }
        if name == "calculate":
            return {"result": calculate(args.get("expression", ""))}
        return {"error": f"Unknown tool {name}"}

    return categories, execute


def _system_prompt(categories: list[str]) -> str:
    return (
        "You are Money Copilot, a private budgeting assistant for a student, running locally. "
        "All money is in EUR. Use the tools to look up the student's budget and past spending. "
        "Never do arithmetic yourself: always use the calculate tool. "
        "To estimate what an activity would cost, find the matching category in the past "
        "transactions, take its average per transaction, multiply by the number of times, and "
        "compare with safe-to-spend. "
        f"Known categories: {', '.join(categories)}. "
        "Reserved expenses are not incoming money. Safe-to-spend is already what remains after "
        "reserving them, so do not tell the student to pay them first from it. "
        "Call the calculate tool for every multiplication or subtraction, and say how much "
        "would remain. If a category has fewer than 5 past transactions, mention that the "
        "estimate is based on little data. "
        "The student also has a live RGB wallet holding STUSD. For any question about the "
        "wallet, the STUSD balance, or sending money with RGB, call get_rgb_wallet_balance and "
        "answer in STUSD, never in EUR. STUSD and the EUR budget are separate and there is no "
        "exchange rate. The app sends the planned rent as the same number of STUSD "
        "(for example 250 STUSD for a 250 EUR rent). You cannot send payments yourself; "
        "payments are made by the student in the RGB Wallet section. "
        "Answer the question directly in 2-4 short sentences, mention the key numbers from the "
        "tool results, and give one practical tip. If you lack information, ask for it."
    )


def _trace_text(trace: list) -> str:
    parts = []
    for step in trace:
        args = ", ".join(f"{k}={v}" for k, v in step["arguments"].items())
        result = json.dumps(step["result"], ensure_ascii=False)
        if len(result) > 140:
            result = result[:140] + "..."
        parts.append(f"{step['name']}({args}) → {result}")
    return " | ".join(parts)


def answer_question(question: str, summary: dict, expenses: list, transactions: list) -> dict:
    if not transactions:
        return {"text": "There are no past transactions to base an answer on yet.", "caption": ""}

    categories, execute = _toolkit(summary, expenses, transactions)
    try:
        text, trace = run_agent(_system_prompt(categories), question, TOOLS, execute)
    except Exception as error:
        return {"text": f"QVAC could not answer the question: {error}", "caption": ""}

    if not text:
        text = "QVAC returned an empty answer. Please try rephrasing the question."

    caption = "Written locally by QVAC."
    if trace:
        caption += " Data it looked up: " + _trace_text(trace)
    else:
        caption += " It did not look up any data for this answer."
    return {"text": text, "caption": caption}