---
name: prototype
description: Build a throwaway prototype to answer a design question. Use when the user wants to sanity-check whether a state model or logic feels right, or explore what a UI should look like.
---

# Prototype

A prototype is **throwaway code that answers a question**. The question decides the shape.

## Pick a branch

Identify which question is being answered from the user's prompt and current context:

- **"Does this logic / state model feel right?"** → [LOGIC.md](LOGIC.md). Build a single shareable HTML file (free-play controls and tabbed guided walkthroughs) that pushes the state model through cases that are hard to reason about on paper, and that a non-developer can drive.
- **"What should this look like?"** → [UI.md](UI.md). Generate several radically different UI variations so the user can compare them and choose or combine a direction.

If the question is ambiguous, ask the user which decision they want the prototype to answer. Do not guess.

## Rules that apply to both

1. **Restate the question.** Before building, restate the specific design question the prototype will answer. Keep the scope narrow enough that the user can make a decision from it.

2. **Match the project context.**
   - If an existing project or UI convention exists, prototype within that context and follow its structure, styling, and conventions.
   - If the relevant project structure or UI does not exist yet, do not create production architecture just to host the prototype. Use a clearly marked standalone prototype instead.
   - For greenfield UI work, use any stack or technical constraints explicitly established in project documentation or the current conversation. If the UI stack is still unknown, ask the user before choosing one.

3. **Keep it trivial to run.** A logic prototype is a single HTML file the user can open directly. A standalone UI prototype should be similarly easy to open or run. If prototyping inside an existing project, use the project's normal development command rather than inventing a separate toolchain.

4. **No persistence by default.** State lives in memory. Persistence is something to prototype only when the question specifically depends on it. If a database or file is required, use clearly disposable local data.

5. **Skip the polish.** No tests, no abstractions, no error handling beyond what makes the prototype runnable and useful.

6. **Surface the state.** After every action (logic) or on every variant switch (UI), print or render the full relevant state so the user can see what changed.

7. **Capture it when done** Once the question is answered, record the chosen direction and why in the current session. Continue the planning conversation using the chosen direction. Keep prototype artifacts in a `prototypes/` directory.