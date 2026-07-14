# Multi-Agent Dormancy Detection Pipeline

A Python pipeline that flags dormant bank accounts from transaction and account data, built using a sequential Claude Code multi-agent workflow (planner → implementer → test-generator → reviewer).

## What it does

The pipeline ingests account and transaction data (core transactions, digital payments, trading activity) and applies dormancy rules to flag accounts with no qualifying activity over a defined period — a common requirement in banking compliance workflows.

## How it was built

This project was developed using four specialized Claude Code subagents running in sequence:

1. **feature-planner** — breaks down dormancy requirements into concrete implementation tasks
2. **code-implementer** — writes the core pipeline logic based on the plan
3. **unit-test-generator** — generates test coverage against expected outputs
4. **data-code-reviewer** — reviews the implementation and data handling for correctness

Agent definitions live in `.claude/agents/`, and prior planning/test context is cached in `.claude/agent-memory/` for reuse across sessions.

## Project structure

```
.
├── .claude/
│   ├── agent-memory/          # cached context from prior agent runs
│   └── agents/                 # agent definitions (planner, implementer, test-gen, reviewer)
├── python/
│   └── dormancy/
│       ├── __init__.py
│       ├── cli.py              # command-line entry point
│       ├── core.py             # core dormancy-flagging logic
│       ├── fixtures/           # sample input data + expected results
│       │   ├── accounts.csv
│       │   ├── core_transactions.csv
│       │   ├── digital_payments.csv
│       │   ├── trading_transactions.csv
│       │   └── expected_dormancy_flags.csv
│       └── tests/
│           ├── conftest.py
│           ├── test_core.py
│           └── test_pipeline.py
└── requirements.txt
```

## Setup

```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
python -m python.dormancy.cli --help
```



## Running tests

```bash
pytest python/dormancy/tests/
```

Tests validate pipeline output against `fixtures/expected_dormancy_flags.csv`.

## Notes

- `node_modules/` and `__pycache__/` are excluded from version control (see `.gitignore`).
- Fixture CSVs are sample/synthetic data for testing — not production account data.
