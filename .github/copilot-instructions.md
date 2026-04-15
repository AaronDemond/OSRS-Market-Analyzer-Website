# GitHub Copilot Instructions

This repository is connected to an Obsidian vault that serves as the project knowledge base.

## Required workflow before making changes
- Before proposing, planning, or making code changes, first consult the **GE Tools** folder in the Obsidian vault.
- Every reference to the **GE Tools** folder must begin at `GE Tools/master_index.md`.
- Do not jump directly into individual notes unless they are reached by navigating from `GE Tools/master_index.md`.
- Treat `GE Tools/master_index.md` as the required entry point for understanding project context, conventions, prior decisions, workflows, and constraints.
- Follow the links and structure from `GE Tools/master_index.md` to find the most relevant notes before acting.

## How to use the vault
- Start at `GE Tools/master_index.md` for every task that may involve:
  - architecture
  - feature design
  - refactoring
  - integrations
  - workflows
  - project conventions
  - prior decisions
- Use the linked structure from the master index to navigate to the relevant topic notes.
- Prefer documented patterns in the vault over inventing new ones.
- If multiple notes are relevant, synthesize them before acting.
- When vault documentation and code appear to conflict, flag the conflict and prefer clarification over guessing.

## Change behavior
- Preserve established architecture, naming, and workflow conventions documented through the `GE Tools/master_index.md` navigation path.
- Prefer updating existing patterns over introducing new ones unless there is a clear reason.
- Avoid duplicate implementations if the vault indicates an existing approach.
- Call out assumptions that are not supported by either the vault or the codebase.

## Documentation behavior
- After meaningful changes, recommend updates to the relevant note(s) in the **GE Tools** folder if the change affects:
  - architecture
  - conventions
  - feature behavior
  - setup steps
  - operational knowledge
  - known issues
- When suggesting documentation updates, place them in the location implied by the structure reached from `GE Tools/master_index.md`.

## If context is missing
- If `GE Tools/master_index.md` or the Obsidian vault is unavailable, explicitly say so before proceeding.
- In that case, make the smallest safe change possible and note that vault context was unavailable.
- If the needed note cannot be reached from `GE Tools/master_index.md`, say that the navigation path is missing rather than guessing.

## Priority
When working in this repository, use this order of precedence:
1. Direct user instructions
2. Obsidian vault documentation reached by starting at `GE Tools/master_index.md`
3. Relevant codebase reality
4. General best practices