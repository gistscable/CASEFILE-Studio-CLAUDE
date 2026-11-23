# Prompts (v2, 2026-11-22)

- `0_Gate_Reviewer_Prompt.md` — a second chat that checks every gate.
- `1_Script_Workflow_Prompts_A_B_and_C.md` — research, footage & soundbite map, script with Re-cut slots, locked package (incl. `recut_plan.md`).
- `2_Guide-Writer_Prompt_for_Casefile_Studio.md` — editing guide + `recut_list.md` in the format `recut.parse` reads.

The three share one rule set; change them together. `tests/test_recut_delete.py` checks that the
recut_list.md format in the Guide-Writer prompt still parses.
