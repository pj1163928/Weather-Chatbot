---
name: implement
description: Build one phase of a feature plan end to end — read the PRD and plan, decide whether to delegate to the tdd skill, implement and test the phase, write a manual test guide, log the session in PROMPTS.md, and offer to commit and push. Works in any language or framework. Use when the user runs /implement.
argument-hint: "<feature> [phase <N>] [tdd|no-tdd] [notes]"
disable-model-invocation: true
---

# Implement

Build one phase of `plans/<feature>.md` against `prd/<feature>.md`, from
reading the plan through to the commit.

This skill is the same for every language and framework. Everything
project-specific comes from the project itself: its `CLAUDE.md`, its docs, its
manifests and its existing code. Never assume a stack the project doesn't use.

## 1. Find the phase

- **Feature**: the first argument (`product-reviews`, or
  `@plans/product-reviews.md`). If none was given, list `plans/` and ask
  which one.
- Read `plans/<feature>.md` and `prd/<feature>.md` in full. If either is
  missing, stop and say which.
- **Phase**: the number given. Otherwise, the first phase that still has an
  unticked acceptance criterion. Check it against
  `git log --oneline` (commits named "Phase N/M of …"). If the two disagree,
  ask.
- Anything else in the arguments is an instruction for this phase and
  outranks the plan. Everything not stated comes from the PRD and plan.
- Run `git status --short` and note any files already modified. They do not
  belong to this phase.

## 2. Gather context

- **The plan and PRD.** Read the plan's architectural decisions, the phase
  itself, and the PRD sections behind the phase's user stories. Where the plan
  says "per the PRD", the PRD's wording is authoritative.
- **The project docs.** Read `CLAUDE.md` if it exists. If it has a "Read
  before…" index, open only the topic files listed for areas this phase
  touches, not whole doc folders. Always read the project's testing doc if one
  exists (often `docs/TESTING.md`).
- **The project's commands.** Find the exact commands for install, run,
  test, lint, format and type-check. Look in this order: `CLAUDE.md`, the
  docs, the README, then the manifests and task runners (for example
  `pyproject.toml`, `package.json` scripts, `Makefile`, `Cargo.toml`,
  `go.mod`, `*.csproj`/`*.sln`, `Gemfile`, `composer.json`) and the CI
  workflows. Use those commands exactly. Never invent one. If the project has
  no tool for a check (no linter, say), skip it and say so in the brief.
- **The code.** Read the code that earlier phases built, and the existing
  pattern closest to the one this phase needs. The plan often names that
  pattern.
- **Updating the docs.** When the phase is built, update the docs as
  `CLAUDE.md`'s "Keeping the docs organized" section says. If there is no
  such section, update any doc the phase made inaccurate.

Fill any gaps from the PRD first, then from the codebase's existing patterns,
then from the language's or framework's idiomatic conventions. Ask only when
the answer is genuinely the user's call and it changes what gets built.

## 3. Decide on TDD

Delegate to the `tdd` skill when the phase has at least one behavior where a
wrong implementation would be costly and easy to miss by eye:

- permissions, privacy, or who can see or change what
- eligibility and business rules
- state transitions, data constraints, or invariants
- calculations, aggregations, parsing, or queries with edge cases
- security: authentication, tokens, secrets, input validation, rate limits,
  audit logging
- a public function in one of the project's core modules (the ones
  `CLAUDE.md` or the plan names as central)

Skip TDD when the phase is only UI layout or styling, copy, seed or fixture
data, configuration or documentation, or when it wires up something that
follows an existing, tested pattern without adding a new rule. If the plan
gives a TDD recommendation for the phase, start from it. If the user passed
`tdd` or `no-tdd`, that overrides this decision.

## 4. Brief, then stop once

Present all of this in one message:

- the phase title, plus a few lines on what will be built
- the areas and files expected to change, including any schema migrations or
  new dependencies
- the commands you will use to test and check the phase (from step 2)
- the decisions you made where the plan left a gap
- the TDD decision: yes or no, with one sentence on why

**With TDD:** invoke the `tdd` skill now and include its behavior list in
this message. The approval it asks for is this step's stop.

**Without TDD:** stop for approval.

After approval, the only further stops are the ones the `tdd` cycles require
and any question that is genuinely the user's call.

## 5. Build

- **Follow the project's conventions.** Use the ones in `CLAUDE.md` and the
  topic docs, and match the surrounding code's structure, naming, error
  handling and test style. Public interfaces get the kind of documentation
  the project already uses (docstrings, JSDoc, XML doc comments and so on).
  Use type annotations where the language and project use them.
- **With TDD**, follow the `tdd` skill's rules for the approved behaviors.
  Every other acceptance criterion still gets ordinary tests, written the way
  the existing tests are.
- **Dependencies.** Add new ones with the project's package manager, pinned
  the way the project pins its others.
- **Schema and data.** If the data model changes, create migrations with the
  project's migration tool. If the phase changes seed or fixture data, run the
  seed twice to confirm it is idempotent.
- **Scope.** Stay inside the phase. If you notice something a later phase
  needs, note it; do not build it.
- **Before finishing**, the full test suite must pass, and the lint, format
  and type-check commands from step 2 must be clean. Never finish red. If
  something will not pass, report it with its output.
- **The plan.** Tick each acceptance criterion (`- [x]`) once it is built and
  either covered by a test or checked by hand. Leave any unmet criterion
  unticked and explain why.

## 6. Manual test guide

Write a guide for the user to follow against the running software, and give
it in the reply, not in a file. Shape it to what the phase changed:

- **Web or desktop UI:** where to go, what to click or type, and what
  should appear.
- **CLI:** the exact commands to run and the expected output.
- **API or service:** example requests (for example `curl`) with the
  expected status codes and response bodies.
- **Library with no runnable interface:** a short script or REPL session
  that exercises the new behavior.

If the phase changes nothing a person can observe beyond the automated tests,
say so in one sentence and skip the guide.

Include:

- **Setup:** the commands to run, in order, taken from step 2. Cover
  installing any new dependencies, applying new migrations, running the seed
  if it changed (warn if it resets data), then starting the app, with the URL
  or entry point.
- **Accounts and data:** if the app has sign-in or roles, say which users to
  use, with credentials taken from the seed or fixture data. Never guess
  them.
- **Walkthroughs:** numbered steps for each scenario. Cover:
  - the happy path
  - each role or user type that sees something different
  - validation errors and invalid input
  - the edge cases named in the acceptance criteria
- **What to look for:** be specific:
  - exact wording or output
  - what changes, and what should *not* (for example, a partial page update
    should not reload the whole page)
  - counts and states after each action
  - for UI changes, any themes or narrow screen widths the project supports
- **Signs of a problem:** the symptoms that would mean something is wrong.
- **Known environment gotchas:** any listed in `CLAUDE.md` or the docs that
  could look like a bug.

Leave out anything the person cannot observe.

## 7. Log the session in PROMPTS.md

When the user runs `/implement`, that is their instruction to log the
session. If `PROMPTS.md` doesn't exist, create it with a short header (a
title, a line saying it records each build session, newest first, and a
closing `---`). Add the new entry at the top: right after the `---` that ends
the header, above every earlier entry. Never edit an older entry. Use this
shape:

    ## YYYY-MM-DD — <Feature>: Phase N/M, <phase title>

    ### Prompts

    1. The `/implement` skill, given `<arguments>`.
    2. Every later prompt, in order, including approvals and corrections.

    ### Summary

    - **Outcome:** what was built; the test count; lint/format/type-check status
    - **Changes:**
      - `path/to/file` — what changed and why
    - **TDD:** the behaviors driven by tests, or why the phase skipped TDD
    - **Decisions:** gaps in the plan that you filled, and how
    - **Deviations:** recommendations the user overrode, follow-up questions
    - **Sideways:** failures and wrong turns, and how they were caught

Write the entry before step 8, so the commit includes it.

## 8. Offer to commit and push

Show `git status --short`. Then propose a commit message that follows the
repo's history:

    Added Phase <N>/<M> of <Feature title> - <what the phase delivers>

For the feature title, use the one that earlier commits for this feature
used. If there are none, use the plan's title.

Ask with AskUserQuestion. Offer "Commit and push", "Commit only" and "Don't
commit".

- Stage files one path at a time; never use `git add -A` or `git add .`.
  - Always stage: the files this phase changed, the plan, and `PROMPTS.md`.
  - Stage only if the user says to:
    - files that were already modified before the phase began (from step 1)
    - local databases, build output or other generated files that are not
      gitignored
    - the PRD, if it is untracked

    List them in the question.
- Never stage secrets (`.env` files, keys, credentials), even if they are
  not gitignored. Warn the user instead.
- Commit on the current branch.
- If the push fails, report the error. Never force-push.
