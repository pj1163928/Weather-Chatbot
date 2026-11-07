---
name: to-prd
description: Turn the current conversation context into a PRD and save it to a local file. Use when user wants to create a PRD from the current context.
---

This skill takes the current conversation context and codebase understanding and produces a PRD. Do NOT interview the user — just synthesize what you already know.

## Process

1. Explore the repo to understand the current state of the codebase, if you haven't already.

2. Use the template below to write the PRD. The PRD should be written in the `prd/prd-name.md` file.

<prd-template>

## Problem Statement

The problem that the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A numbered list of user stories. Each user story should be in the format of:

1. As an <actor>, I want a <feature>, so that <benefit>

<user-story-example>
1. As a mobile bank customer, I want to see balance on my accounts, so that I can make better informed decisions about my spending
</user-story-example>

This list of user stories should be thorough and cover all agreed aspects of the feature without inventing new scope.

## Implementation Decisions

A list of implementation decisions that were made. This can include:

- The apps or components that will be built/modified
- The views, forms, models, or other components that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Model and database changes
- URL and form behavior
- Specific interactions

Do NOT include specific file paths or code snippets. They may end up being outdated very quickly.

## Out of Scope

A description of the things that are out of scope for this PRD.

## Further Notes

Any further notes about the feature.

</prd-template>