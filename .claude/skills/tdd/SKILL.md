---
name: tdd
description: Develop a small number of important behaviors from an approved plan phase using test-driven development, or say plainly when the phase has no good candidates. Use only when the user asks for TDD by name or the implement skill delegates to it.
argument-hint: "@prd/<feature>.md @plans/<feature>.md implement phase <N>"
---

# TDD

Use test-driven development for a small number of important behaviors in the
current phase. The rest of the phase still follows the project's normal
implementation and testing process.

## 1. Select the behaviors

Before writing code, pick **at most three** behaviors from the phase's
acceptance criteria — the ones a test can clearly describe. Take fewer if the
phase offers fewer, and none if it offers none: a phase of configuration,
copy, seed data, or documentation has no candidates, and neither does a
behavior whose interface an existing, tested pattern has already settled.

Present them as a numbered list, one sentence each on why it is a good TDD
candidate. Do not list what you rejected. If nothing qualifies, say so in one
sentence with the reason — an empty set is a legitimate answer, not a failure
to find three. Stop for approval either way.

## 2. Run each cycle

Build the phase in its natural order. On reaching a selected behavior, once
enough is built for a test to run:

1. Write one test for the behavior.
2. Run it. **RED means it fails on an assertion** — anything else means the
   scaffolding is not there yet: build what is missing and re-run.
3. Show the test, why it failed, and what passing will prove. This test is now
   the definition of correct — you will make *this* pass, so the user should
   change it now if it describes the wrong thing. Stop for approval.
4. Write only enough code to pass.
5. Run the test again and confirm it passes. This is GREEN.
6. Run the relevant existing tests to check for regressions.
7. Summarize briefly what made the test pass. Ask whether it implements the
   behavior or only satisfies the test. Stop before moving on.

Then move to the next behavior.

## Rules

- One behavior and one test at a time.
- Test observable behavior, not implementation details.
- After approval, a mechanical repair to a test gets a one-line note;
  a change to what it asserts goes back for re-approval.
- TDD applies only to the approved behaviors. All other requirements still need
  normal implementation and testing.
- Do not force TDD onto styling, documentation, or anything without a clear
  testable behavior.