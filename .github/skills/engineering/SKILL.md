---
name: engineering-skill-set
description: "Project-local engineering agent skill set for frontend, backend, architecture, writing, Git, and specialist workflows. Use when you want Copilot to follow a specific engineering role from the bundled agent files under .github/skills/engineering/agents/."
---

# Engineering Skill Set

This skill bundle adds the project-local engineering agent set to COMP5541.

## Included Agents

The full reference set lives in [agents/](agents/):

- [Frontend Developer](agents/engineering-frontend-developer.md)
- [Backend Architect](agents/engineering-backend-architect.md)
- [AI Engineer](agents/engineering-ai-engineer.md)
- [Senior Developer](agents/engineering-senior-developer.md)
- [Technical Writer](agents/engineering-technical-writer.md)
- [Code Reviewer](agents/engineering-code-reviewer.md)
- [Git Workflow Master](agents/engineering-git-workflow-master.md)
- [Software Architect](agents/engineering-software-architect.md)
- [Minimal Change Engineer](agents/engineering-minimal-change-engineer.md)
- [SRE](agents/engineering-sre.md)

## How To Use

Use the agent that matches the task:

- UI and React work: Frontend Developer
- API design, schemas, and service logic: Backend Architect
- Cross-cutting system design: Software Architect
- Docs, README files, and tutorials: Technical Writer
- Cleanups, refactors, and smallest-safe diffs: Minimal Change Engineer
- Commit strategy, branches, and rebase workflows: Git Workflow Master
- Review quality, risks, and regressions: Code Reviewer

## Prompt Examples

- "Use the Frontend Developer agent to redesign this page for mobile and accessibility."
- "Use the Backend Architect agent to design the upload endpoint and service contract."
- "Use the Technical Writer agent to rewrite the README as a quick-start guide."
- "Use the Senior Developer agent to implement the feature with minimal churn."
- "Use the Code Reviewer agent to review this diff for regressions."

## Notes

- The agent files are reference documents bundled with the repo.
- Keep the naming aligned with the engineering folder so the skill set is easy to browse and reuse.
- If you add new specialist agents later, place them in `agents/` and link them here.
