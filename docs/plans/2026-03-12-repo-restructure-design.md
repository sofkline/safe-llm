# Repo Restructure Design — 2026-03-12

## Context
Safe LLM repo was a flat collection of research docs, thesis topics, and meeting transcripts. Restructured into a shared workspace for 3 contributors (supervisor + 2 students).

## Decisions
- **Hybrid structure**: shared `research/` folder + per-topic folders (`behavioral-monitoring/`, `crisis-detection/`)
- **Topic folders by topic name**, not student name
- **Meeting transcripts kept** with raw files (renamed from `transritbs-and-summaryes`)
- **Three link files merged** into single `research/resources.md`
- **Both EN/RU psychology guides kept**
- **Inactive topics archived** to `archive/`
- **Mikhail's code repo cloned and gitignored** — students keep their own code repos

## Structure
```
safe-llm/
├── research/                          # Shared research
├── behavioral-monitoring/             # Sophiya (Topic 2)
├── crisis-detection/                  # Mikhail (Topic 3)
├── meetings/                          # Transcripts & summaries
├── archive/                           # Inactive materials
└── ai-safety-mikhail/                 # Cloned, gitignored
```
