# UI Prototype

Generate **several radically different UI variations** so the user can compare them in the browser, choose one, or combine parts from several.

If the question is about logic/state rather than what something looks like, this is the wrong branch. Use [LOGIC.md](LOGIC.md).

## When this is the right shape

- "What should this page look like?"
- "I want to see a few options for this dashboard before committing."
- "Try a different layout for the settings screen."
- "This is a new project. What should the UI convention be?"
- Any time a visual or interaction decision is easier to judge by seeing alternatives than discussing them in text.

## First determine the project context

Before generating variants, determine whether the project already has an established UI convention.

### Existing UI: prototype within the convention

If an established UI exists, use its real context: page shell, navigation, typography, spacing, components, data density, styling system, and interaction patterns.

Prefer an existing page when one can reasonably host the prototype. Keep the route, data fetching, params, auth, and surrounding UI intact. Swap only the uncertain part.

If the feature has no existing page, create a clearly marked throwaway prototype using the project's existing routing and UI conventions. Do not invent a second design system just for the prototype.

### No existing UI: establish the convention

If the project has no established UI, the prototype's purpose is to help the user **choose the project's UI convention before production pages are built**.

First determine the intended UI stack in this order:

1. project documentation such as `CLAUDE.md` or the README
2. UI-stack constraints explicitly stated in the current conversation
3. if still unknown, ask the user before generating variants

Do not guess the stack.

Create several radically different versions of the UI target the user asked to explore. If no specific target was given and the project has no established UI convention, use a representative application page to help establish that convention. Use realistic domain content and enough common UI elements to judge:

- navigation and page shell
- information hierarchy and density
- typography and spacing
- cards, tables, forms, buttons, and status indicators where relevant
- primary actions and interaction patterns
- responsive behavior

Do **not** scaffold or restructure the production application merely to host the prototype. Create a clearly marked standalone prototype, such as `prototypes/ui-convention.html`, that can be opened directly in the browser.

If the intended production UI stack is known, use a lightweight standalone version of that stack when possible. For example, a Tailwind/DaisyUI project may use their browser/CDN setup in the prototype without creating the production Django or asset pipeline. If the stack is unknown, ask the user rather than silently choosing one.

Start with one representative page. Add a second only when an important convention cannot be judged from the first.

## Process

### 1. State the question and pick N

Default to **3 variants**. Cap at 5.

Write the prototype question in one line. Examples:

> "Three variants of the existing settings page, preserving the current project shell."

> "Three radically different ATS dashboard directions to establish the project's UI convention."

### 2. Generate radically different variants

Each variant must satisfy the same user goal and use realistic content.

Variants must be **structurally different**: different layout, information hierarchy, navigation, density, or primary affordance. Different colours, copy, border radius, or slightly altered card grids do not count.

When an existing UI convention exists, preserve it while varying the uncertain design decision.

When no convention exists, deliberately explore different project directions. For example, one variant might use a dense sidebar dashboard, another a workflow-centered workspace, and another a restrained list/detail interface.

If two drafts are too similar, redo one.

### 3. Make variants easy to compare

Present all variants through one prototype and provide a small, visually separate switcher.

The switcher should:

- cycle backward and forward through variants
- show the current variant key and short name
- support keyboard `←` and `→` when focus is not inside an input
- keep the selected variant stable on reload when practical
- remain visually distinct from the design being evaluated

Adapt the switcher to the existing project when one exists. In a standalone greenfield prototype, use plain HTML/JS plus the declared UI stack when it can run without production scaffolding. Do not introduce an unrelated framework, bundler, server, or production dependency solely for the prototype.

### 4. Keep prototype behavior safe

Use realistic data, but do not wire variants to real destructive mutations. Stub interactions or keep state in memory unless the interaction itself is what needs to be evaluated.

Surface enough state or feedback that the user can understand what each interaction does.

### 5. Hand it over and iterate

Show the user how to open the prototype and switch variants.

Useful feedback often combines ideas:

> "Use B's navigation, C's information density, and A's form layout."

Revise or add a variant when needed. The goal is a decision, not a winner on the first pass.

### 6. Capture the answer and clean up

Once the prototype answers its question, record the chosen direction and why, then capture the prototype the way the [SKILL](SKILL.md) describes.

## Anti-patterns

- **Variants that differ only in colour or copy.** Real variants disagree about structure or interaction.
- **Ignoring an existing UI convention.** Prototype the uncertain part without redesigning the whole project.
- **Creating production architecture to host a greenfield prototype.** The prototype should help choose conventions before production structure depends on them.
- **Using a different UI framework merely to create variety.** Variants should disagree about design, not change the project's technical stack.
- **Sharing so much layout code that every variant looks the same.** Reuse only what should truly remain constant.
- **Wiring variants to real mutations.** Use stubs or in-memory state unless mutation behavior is the question.