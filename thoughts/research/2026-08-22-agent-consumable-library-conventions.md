# Research: Conventions for making a library consumable by AI coding agents

**Date:** 2026-08-22
**Branch:** master
**Companion:** `thoughts/research/2026-08-22-ai-agent-discoverability.md`
(the ActingWeb-specific audit that acts on these findings)

State of play, August 2026: what actually works when an open-source library wants
to be implementable by AI coding agents working in *consumer* repositories.

**Evidence tiers used throughout:** `[PRIMARY]` = vendor/spec doc or source repo · `[MEASURED]` = study with methodology · `[SECONDARY]` = commentary. Untraceable claims are labelled as such and not used as findings.

**Not independently re-verified.** The mechanics below — the Agent Skills schema,
`npx skills add owner/repo`, the Laravel Boost third-party convention — are taken
from the primary sources cited. Confirm them before building on them.

---

## Headline Answers

1. **No coding agent auto-fetches `llms.txt` at runtime.** Every "Cursor/Copilot/Claude Code reads llms.txt" claim collapses to user-initiated ingestion or manual paste. Cursor's own staff logged it as an unimplemented feature request in June 2025, still open.
2. **AGENTS.md is structurally repo-scoped to *contributors*.** Its own resolution rule ("closest file to the edited file") means a library's AGENTS.md can never reach a downstream consumer's agent. This is decided by mechanism, not opinion.
3. **The only working consumer-facing mechanisms are skill/plugin distribution** — `agentskills.io` + `npx skills add owner/repo`, Claude Code `marketplace.json`, and Laravel Boost's third-party package convention.
4. **Laravel Boost is the only mature "library ships agent guidance to consumers" system, and it has no Python/PyPI equivalent.** That is the actionable gap.
5. **The one rigorous study measuring context files found they do *not* help — but it measures the contributing case, not the consuming case.** No study measures the consuming case at all.

---

## The Frame That Decides Q1: Three Tiers of "Consumption"

Vendors and SEO blogs deliberately blur these. Separating them resolves the question:

| Tier | Definition | Anything here? |
|---|---|---|
| **Tier 1** | Agent auto-discovers and fetches `/llms.txt` at runtime, no user action | **Nothing. Zero evidence.** |
| **Tier 2** | Tool ingests llms.txt *if present* when a user explicitly supplies a docs URL | `langchain-ai/mcpdoc`; Context7 (separate mechanism) |
| **Tier 3** | Human manually pastes `llms-full.txt` into context | Ubiquitous, unmeasurable |

**The crux question is Tier 1. The answer is: no evidence, and one primary-source negative.**

---

## 1. `llms.txt` / `llms-full.txt`

### Spec status `[PRIMARY]`
- [llmstxt.org](https://llmstxt.org/) — **Version 2**, published 3 Sep 2024, **last modified 10 Aug 2026** (actively maintained). Author **Jeremy Howard** (Answer.AI). Repo: [AnswerDotAI/llms-txt](https://github.com/answerdotai/llms-txt).
- The spec is **advocacy about its own adoption**, and should be read as such. It asserts: *"Agents are expected to view or search `llms.txt`… then follow the relevant links"* and *"coding agents follow them to find API references."* **"Expected to" is not "do."** No vendor documentation corroborates the runtime-fetch claim.

### Does any coding agent fetch it? — the Tier 1 answer
- **Cursor: documented NO.** `[PRIMARY]` Feature request ["Cursor not support llms.txt standard"](https://forum.cursor.com/t/cursor-not-support-llms-txt-standard/108980) — Cursor staff **Dan Perks, 25 June 2025**: *"does seem like something we should support! I've logged this down for the team to look into soon."* No implementation announced since. Corroborating user reports that supplying an llms.txt URL to @Docs [indexes nothing](https://forum.cursor.com/t/indexing-https-llmstxt-org-format-to-docs/62833).
- **Claude Code, Copilot, Codex: no documentation either way.** These are closed tools; absence of a documented feature is weak evidence, and that asymmetry is stated rather than papered over.
- **Tier 2 exists and is real:** [`langchain-ai/mcpdoc`](https://github.com/langchain-ai/mcpdoc) `[PRIMARY]` — an MCP server that exposes *"a user-defined list of llms.txt files"* with a `fetch_docs` tool. Note **user-defined**: the agent does not discover the file, the human configures it. This is the clearest proof of the Tier 1/Tier 2 boundary.

### The one genuinely new development: Google Lighthouse `[PRIMARY]`
This materially changes the "proposed but little-used" read and is the most consequential 2026 datum:
- Chrome shipped an **Agentic Browsing** audit category in **Lighthouse, from M150**, which includes an [**llms.txt audit**](https://developer.chrome.com/docs/lighthouse/agentic-browsing/llms-txt).
- Important caveats, from Google's own page: the file is *"an emerging convention"*, *"providing the file is optional at the moment"*, a 404 marks the audit **Not Applicable** rather than failing, and the [category has no weighted 0–100 score](https://developer.chrome.com/docs/lighthouse/agentic-browsing/scoring) because *"standards for the agentic web are still emerging."*
- So: Google now *audits for* llms.txt. That is not the same as any Google product *consuming* it. There is a [known bug where the audit fails spec-compliant files](https://github.com/GoogleChrome/lighthouse/issues/17082).

### Measured adoption `[MEASURED]`
- [SE Ranking, "LLMs.txt: Why Brands Rely On It and Why It Doesn't Work"](https://seranking.com/blog/llms-txt/) — ~300,000 domains, **10.13% adoption**. Adoption is flat across traffic tiers (9.88% low, 10.54% mid, **8.27% high** — the largest sites are *less* likely to have one). On citations: *"Having an LLMs.txt file didn't make a domain more likely to be cited by AI models; in fact, the model performed better without it."*
- ⚠️ **Untraceable — do not cite:** the widely-repeated "500M AI bot visits, only 408 requested llms.txt" figure and a "John Mueller, June 2025" quote both appeared in AI-generated search summaries with **no locatable publisher**; neither could be traced. (The Mueller claim also concerns AI *search*, a different question from coding agents.)

### Docs platform support — all four checked
| Platform | Status | Evidence |
|---|---|---|
| **Read the Docs** | **Serves it; does NOT auto-generate** | `[PRIMARY]` [RTD blog, 11 Feb 2026](https://about.readthedocs.com/blog/2026/02/llms-txt-support/): *"add llms.txt (and optionally llms-full.txt) to your build output using your documentation tool."* Also supports **Markdown content negotiation** so agents fetch clean text without scraping HTML. |
| **Mintlify** | **Auto-generates AND actively advertises it** | `[PRIMARY]` — *direct observation:* two Mintlify-hosted sites, when fetched, injected a header into the page body: *"## Documentation Index — Fetch the complete documentation index at: …/llms.txt."* Seen on [code.claude.com/docs](https://code.claude.com/docs/en/memory) and [agentskills.io](https://agentskills.io/). Mintlify nudges any agent that fetches *any* page toward llms.txt. This is the strongest real-world push mechanism found. |
| **Docusaurus** | **Community plugins only; no core support** | `[PRIMARY]` [rachfop/docusaurus-plugin-llms](https://github.com/rachfop/docusaurus-plugin-llms), [din0s/docusaurus-plugin-llms-txt](https://github.com/din0s/docusaurus-plugin-llms-txt). Official support is an [open issue, facebook/docusaurus#10899](https://github.com/facebook/docusaurus/issues/10899). |
| **VitePress** | **Community plugins only** | `[PRIMARY]` [okineadev/vitepress-plugin-llms](https://github.com/okineadev/vitepress-plugin-llms) |

### ⭐ Directly relevant to this project (Sphinx + RTD)
**[`sphinx-llms-txt`](https://pypi.org/project/sphinx-llms-txt/) `[PRIMARY]` — v0.7.1, released 16 Dec 2025**, MIT, maintained by **Jared Dillard** (Read the Docs). Generates *"a summary `llms.txt` file and a single combined documentation `llms-full.txt` file"*, marked parallel-safe. Source: [jdillard/sphinx-llms-txt](https://github.com/jdillard/sphinx-llms-txt).

**This is a drop-in for ActingWeb**: `sphinx-llms-txt` produces the files, RTD serves them at the domain root. Cost is near-zero. Expected benefit is Tier 2/3 only — it helps a human who points a tool at your docs; it will not be auto-discovered.

---

## 2. `AGENTS.md` — and the contributing-vs-consuming crux

### Facts `[PRIMARY]`, all from [agents.md](https://agents.md/) and [openai/agents.md](https://github.com/openai/agents.md)
- Purpose: *"a **README for agents**: a dedicated, predictable place to provide the context and instructions to help AI coding agents **work on your project**."*
- Explicit README split: *"README.md files are for humans… AGENTS.md contains the extra, sometimes detailed context coding agents need: **build steps, tests, and conventions**."*
- **Adoption: "over 60,000 open-source projects"** — verified on the site itself, not a secondary source.
- **Stewardship: the Agentic AI Foundation, under the Linux Foundation** — verified on the site.
- Supporting tools listed: OpenAI Codex, Google Jules, Factory, Aider, goose, opencode, Zed, Warp, VS Code, Devin, JetBrains Junie, Amp, Cursor, RooCode, Gemini CLI, GitHub Copilot, Windsurf, Augment Code, Semgrep, UiPath, and others.

### ✅ The crux, settled by mechanism not opinion
The open question was whether AGENTS.md is for agents **contributing to** the repo or **consuming** the library. Three independent primary sources converge on **contributing**:

1. **The spec's own resolution rule** `[PRIMARY]` — agents.md FAQ: *"Agents automatically read the **nearest file in the directory tree**, so the closest one takes precedence"* and *"**The closest AGENTS.md to the edited file wins**."* Resolution is anchored to the **file being edited**. A consumer's agent edits files in *their* repo, never in your library. Your shipped AGENTS.md is unreachable by construction.
2. **The stated content type** — build steps, tests, PR instructions, code style. All contributor concerns. None are usable by someone merely *calling* your API.
3. **Claude Code doesn't read it at all** `[PRIMARY]` — [Claude Code memory docs](https://code.claude.com/docs/en/memory) state flatly: *"**Claude Code reads `CLAUDE.md`, not `AGENTS.md`.**"* Recommended workaround is an `@AGENTS.md` import or a symlink. (This resolves a self-contradiction present in AI-generated search summaries, which claimed both that Claude Code reads AGENTS.md and that it doesn't.)

**Conclusion: `AGENTS.md` is the wrong tool for consumer-facing guidance. There is no "AGENTS.md for consumers" convention.** Shipping one in a wheel is inert.

### Corollary — wheel-shipped instruction files — *inference from two primary specs*
Claude Code loads subdirectory `CLAUDE.md` **only "when Claude reads files in those directories"**; AGENTS.md resolves to the closest file to the **edited** file. Therefore a `CLAUDE.md`/`AGENTS.md` shipped inside a wheel is reachable **only if the consumer's agent happens to read files in `site-packages`** — not a designed path, and virtualenvs usually sit outside the project tree entirely. *This is inference from the resolution rules above, not a sourced claim.* **No library was found doing this deliberately.**

---

## 3. Shipping Docs to Consumers — What Actually Works

### ⭐ 3a. Agent Skills — the real answer `[PRIMARY]`
[**agentskills.io**](https://agentskills.io/) — *"originally developed by Anthropic, released as an open standard,"* now vendor-neutral. Repo: [agentskills/agentskills](https://github.com/agentskills/agentskills).

- A skill is a folder with `SKILL.md` (YAML frontmatter: `name`, `description`) plus optional `scripts/`, `references/`, `assets/`.
- **Progressive disclosure** — three stages: *Discovery* (only name+description at startup), *Activation* (full SKILL.md when the task matches), *Execution*. **This is the key architectural property for a library**: you can ship substantial guidance at near-zero idle context cost, which directly addresses the cost objection raised by the study in §5.
- Supported by ~45 listed clients including Claude Code, Cursor, GitHub Copilot, VS Code, Codex/ChatGPT, Gemini CLI, goose, OpenHands, Junie, Amp, Factory, Roo Code, Kiro, opencode.

**Can a library publish a skill consumers install? YES — three working distribution paths:**

1. **Agent Skills CLI, any GitHub repo** `[PRIMARY]` — `npx skills add owner/repo`. Real example: Read the Docs ships [readthedocs/skills](https://github.com/readthedocs/skills), announced [11 Feb 2026](https://about.readthedocs.com/blog/2026/02/readthedocs-skills-api-config/), including a skill for their REST API and one for authoring `.readthedocs.yaml`. **A docs platform shipping skills to its users is precisely the library→consumer pattern.**
2. **Claude Code plugin marketplaces** `[PRIMARY]` — [plugin marketplace docs](https://code.claude.com/docs/en/plugin-marketplaces): *"A plugin marketplace is a catalog that lets you distribute plugins to others."* You define a **`marketplace.json`**, *"push to GitHub, GitLab, or another git host"*, and users run `/plugin marketplace add`. **Any third party can host one — a library's own repo can be the distribution point.** Plugins bundle skills, agents, hooks, MCP servers, and LSP servers.
3. **Ecosystem package managers** — see Laravel Boost below.

### ⭐ 3b. Laravel Boost — the exemplar, and the Python gap `[PRIMARY]`
[Laravel Boost](https://laravel.com/docs/12.x/boost) is the most complete implementation of "framework makes itself agent-implementable," and it is worth studying closely:

- Consumer installs: `composer require laravel/boost --dev` then `php artisan boost:install`, which generates guideline/skill files for whichever agents the user selects (Claude Code, Cursor, Codex, Gemini CLI, Copilot, Junie).
- **Three distinct layers**, an important design lesson:
  - **AI Guidelines** — loaded **upfront**, broad conventions, **version-specific** (Laravel 10.x/11.x/12.x, Livewire 2.x/3.x/4.x…).
  - **Agent Skills** — loaded **on-demand**, task-specific, explicitly *"reducing context bloat."*
  - **MCP server** — live introspection tools: Application Info, Database Schema/Query, Read Log Entries, Last Error, Browser Logs, **Search Docs**.
- **Documentation API**: *"over 17,000 pieces of Laravel-specific information… semantic search with embeddings"*, queried via the `Search Docs` MCP tool.
- 🔑 **Third-party package convention** — the mechanism in question: a package adds `resources/boost/guidelines/core.blade.php` and/or `resources/boost/skills/{skill-name}/SKILL.md`, and *"when users of your package run `php artisan boost:install`, Boost will automatically load your guidelines"* / install your skills. Skills auto-install based on packages detected in `composer.json`.
- **Real third-party adoption:** Spatie, a major package vendor, [ships a Boost skill for laravel-sluggable](https://spatie.be/docs/laravel-sluggable/v4/laravel-boost-skill). Also a community directory, [Laravel Skills](https://laravelmagazine.com/laravel-skills-a-public-directory-of-ai-agent-skills-for-laravel-php).

**🚨 There is no Python/PyPI equivalent of Boost's auto-discovery.** Nothing scans installed distributions for bundled skills and installs them into the consumer's agent config. **This is the single clearest actionable gap for ActingWeb** — and, notably, an open opportunity.

### 3c. Docs-as-MCP `[PRIMARY]`
- **Context7** — operated by **Upstash**: [upstash/context7](https://github.com/upstash/context7). Serves *"current, version-specific documentation and code examples directly into LLM prompts."* Parsing/crawling backend is **proprietary and closed**.
  - Indexing is **self-serve and requires no ownership**: submit a public GitHub URL at [context7.com/add-library](https://context7.com/docs/adding-libraries); *"Anyone can add a public library — you don't need to own it."* Library ID format `/org/project`. A committed **`context7.json`** gives finer parsing control.
  - **Not llms.txt-driven** — a separate indexing pipeline. Worth noting for ActingWeb: **anyone could already have listed you, or you can list yourself in minutes.**
- **`langchain-ai/mcpdoc`** — the llms.txt→MCP bridge described in §1, with per-domain allowlisting for security.
- **Vendor-run docs MCP** — LangChain [exposes MCP servers over its own docs](https://docs.langchain.com/use-these-docs). Combined with Boost, this is a genuine emerging pattern: *libraries running an MCP server over their own documentation.*

### 3d. `py.typed` / inline types — **negative finding**
**No writing was found that measures how much type hints help coding agents.** Searches returned only Pydantic-AI tutorials and general "typed Python is good" advocacy ([Pyrefly blog](https://pyrefly.org/blog/why-typed-python/)), none of which addresses `py.typed` as an *agent affordance*. The mechanism is plausible — a typed library gives an agent checkable ground truth, and a type error is a fast feedback signal an agent can act on — but **this is an untested hypothesis, not an evidenced convention.** ActingWeb already ships strict typing; treat it as sound engineering, not as an evidenced agent feature.

---

## 4. Python / PyPI Specifics — **strong negative finding**

- **There are no AI/agent/MCP trove classifiers.** `[PRIMARY]` Checked against the canonical list at [pypa/trove-classifiers](https://github.com/pypa/trove-classifiers/) and [pypi.org/classifiers](https://pypi.org/classifiers/). The **only** relevant classifier is the long-standing `Topic :: Scientific/Engineering :: Artificial Intelligence`. **No** `Agent`, `MCP`, `Model Context Protocol`, or `LLM` classifier exists.
- **The MCP classifier proposal is stalled.** `[PRIMARY]` [PR #207, "Add classifier for Model Context Protocol"](https://github.com/pypa/trove-classifiers/pull/207), proposing `Framework :: Model Context Protocol`, opened **14 March 2025** — **still open and undecided ~17 months later**. A contributor suggested escalating to discuss.python.org; no maintainer decision has been rendered.
- **Consequence:** there is **no PyPI-side metadata channel** to advertise AI/MCP capability. Keywords in `pyproject.toml` (e.g. `mcp`, `ai-agent`) are free-text and unstandardised — usable, but they carry no ecosystem semantics and nothing consumes them structurally.

---

## 5. Does Any of This Actually Work? `[MEASURED]`

### The one rigorous study — and its critical scope limit
**Gloaguen, Mündler, Müller, Raychev, Vechev — ["Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?"](https://arxiv.org/abs/2602.11988)**, arXiv 2602.11988, submitted **12 Feb 2026**, revised 23 June 2026. (ETH Zurich / LogicStar group — a credible source, not an SEO blog.)

Abstract, verbatim: *"A widespread practice in software development is to tailor coding agents to repositories using context files, such as AGENTS.md. Although this practice is strongly encouraged by agent developers, there is currently no rigorous investigation into whether such context files are actually effective for real-world tasks."*

**Findings:**
- Context files **did not generally improve task success rates**.
- **Inference costs rose by over 20% on average.**
- Results held across multiple LLMs and coding agents.
- 🔑 **Most useful nuance: *instructions within context files were well-followed, but repository overviews — the thing most commonly recommended — were unhelpful.***
- Conclusion: context files are useful for *"specifying non-standard coding practices"*, but claimed gains *"require rigorous evaluation before deployment."*

Reported benchmark details (from secondary coverage of the paper — [DAIR.AI](https://academy.dair.ai/blog/agents-md-evaluation), [arxiviq](https://arxiviq.substack.com/p/evaluating-agentsmd-are-repository)): **AGENTbench**, 138 tasks across 12 real Python repos with developer-committed context files; agents tested included Claude Code (Sonnet 4.5), Codex (GPT-5.2, GPT-5.1 Mini), Qwen Code. LLM-generated files ≈ −0.5% on SWE-bench Lite and ≈ −2% on AGENTbench; developer-written ≈ +4% but up to +19% cost. *These specific per-condition numbers could not be confirmed on the arXiv abstract page itself — treat the headline directional findings as solid and the precise percentages as secondary.*

### ⚠️ Scope limit — read this before applying the numbers
**This study measures the *contributing* case**: agents fixing issues **inside** the repo that owns the context file. **It says nothing about the consuming case** — an agent in a downstream repo writing code against your library. Do not conclude from it that shipping consumer-facing agent docs is counterproductive; that inference is not supported.

**There is a second related paper**, ["On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents"](https://arxiv.org/html/2601.20404v2) (arXiv 2601.20404), not reviewed in depth.

### The honest Q5 answer
**No study, benchmark, or post-mortem was found measuring whether *any* of these artifacts — llms.txt, skills, docs-MCP, wheel-shipped docs — improve agent success at implementing against a third-party library from a downstream repo.** The entire consumer-facing category is **unmeasured**. Everything advocating it (including llmstxt.org and Boost's marketing) is advocacy, not evidence.

The one transferable signal: **concrete, actionable instructions get followed; general overviews are dead weight.** That argues for narrow task-shaped skills ("how to add an ActingWeb property hook") over a prose architecture tour.

---

## Explicit Negative Findings

| Claim | Verdict |
|---|---|
| A coding agent auto-fetches `/llms.txt` at runtime (Tier 1) | **No evidence.** Cursor documented as not supporting it; no vendor documents it. |
| AGENTS.md reaches consumers of a library | **Refuted by mechanism** — resolution is anchored to the edited file. |
| Claude Code reads AGENTS.md | **False** — *"Claude Code reads `CLAUDE.md`, not `AGENTS.md`."* |
| PyPI has AI/MCP/agent classifiers | **None.** MCP proposal open & stalled since March 2025. |
| Python has a Laravel Boost equivalent | **None found.** |
| Anyone deliberately ships markdown docs in a wheel for agents | **None found**; mechanically near-unreachable anyway. |
| Writing measuring `py.typed` as an agent affordance | **None found.** |
| Measured evidence for the *consumer-facing* case | **None exists.** |
| "500M bot visits / 408 llms.txt requests"; "Mueller June 2025" | **Untraceable — not used.** |

---

## Implications for ActingWeb (Sphinx + RTD, Python, ships an MCP server)

Ranked by evidence strength ÷ cost. Note the asymmetry: the *cheap* items are evidenced-neutral, the *valuable* items are unmeasured but structurally sound.

1. **`sphinx-llms-txt` + RTD** — hours of work, zero risk, immediate Tier 2/3 benefit and a passing Lighthouse audit. Do not expect Tier 1 discovery. **Highest confidence, modest ceiling.**
2. **List ActingWeb on Context7** — minutes, self-serve, no ownership check; add `context7.json` to control parsing. Someone may have listed you already.
3. **Publish an Agent Skill for *consumers*** — a `SKILL.md` teaching "how to build an app on ActingWeb," distributed from your own repo via `npx skills add` and/or a `marketplace.json`. **This is the only mechanism that actually targets the consuming case.** Progressive disclosure means it costs a consumer ~nothing until it activates. Follow the study's lesson: concrete task recipes (hooks, trust setup, property lookup), **not** an architecture overview.
4. **Lean on the MCP server you already have** — Boost's design says the winning combination is *guidelines + on-demand skills + live MCP introspection*. ActingWeb already has the third leg, which most Python libraries do not.
5. **Do NOT** ship AGENTS.md/CLAUDE.md in the wheel for consumers — inert by construction. Keep `CLAUDE.md` where it is: contributor guidance, which is exactly what it's for and what this repo already does correctly.
6. **Watch** trove-classifiers PR #207; add free-text `mcp`/`agent` keywords meanwhile as a no-cost hedge.

---

## Sources

**Specs & standards:** [llmstxt.org](https://llmstxt.org/) · [AnswerDotAI/llms-txt](https://github.com/answerdotai/llms-txt) · [agents.md](https://agents.md/) · [openai/agents.md](https://github.com/openai/agents.md) · [agentskills.io](https://agentskills.io/) · [agentskills/agentskills](https://github.com/agentskills/agentskills)

**Vendor docs:** [Claude Code memory](https://code.claude.com/docs/en/memory) · [Claude Code plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) · [Lighthouse llms.txt audit](https://developer.chrome.com/docs/lighthouse/agentic-browsing/llms-txt) · [Lighthouse agentic scoring](https://developer.chrome.com/docs/lighthouse/agentic-browsing/scoring) · [Lighthouse issue #17082](https://github.com/GoogleChrome/lighthouse/issues/17082) · [Laravel Boost](https://laravel.com/docs/12.x/boost) · [LangChain docs-as-MCP](https://docs.langchain.com/use-these-docs)

**Read the Docs:** [llms.txt support, 11 Feb 2026](https://about.readthedocs.com/blog/2026/02/llms-txt-support/) · [Agent skills, 11 Feb 2026](https://about.readthedocs.com/blog/2026/02/readthedocs-skills-api-config/) · [readthedocs/skills](https://github.com/readthedocs/skills)

**Tooling:** [sphinx-llms-txt (PyPI)](https://pypi.org/project/sphinx-llms-txt/) · [jdillard/sphinx-llms-txt](https://github.com/jdillard/sphinx-llms-txt) · [langchain-ai/mcpdoc](https://github.com/langchain-ai/mcpdoc) · [upstash/context7](https://github.com/upstash/context7) · [Context7 adding libraries](https://context7.com/docs/adding-libraries) · [docusaurus-plugin-llms](https://github.com/rachfop/docusaurus-plugin-llms) · [docusaurus-plugin-llms-txt](https://github.com/din0s/docusaurus-plugin-llms-txt) · [docusaurus#10899](https://github.com/facebook/docusaurus/issues/10899) · [vitepress-plugin-llms](https://github.com/okineadev/vitepress-plugin-llms)

**PyPI:** [pypa/trove-classifiers](https://github.com/pypa/trove-classifiers/) · [PR #207 (MCP, open)](https://github.com/pypa/trove-classifiers/pull/207) · [pypi.org/classifiers](https://pypi.org/classifiers/)

**Studies:** [Gloaguen et al., arXiv 2602.11988](https://arxiv.org/abs/2602.11988) · [arXiv 2601.20404](https://arxiv.org/html/2601.20404v2) · [SE Ranking llms.txt study](https://seranking.com/blog/llms-txt/)

**Third-party adoption:** [Spatie laravel-sluggable Boost skill](https://spatie.be/docs/laravel-sluggable/v4/laravel-boost-skill) · [Laravel Skills directory](https://laravelmagazine.com/laravel-skills-a-public-directory-of-ai-agent-skills-for-laravel-php)

**Secondary (paper coverage only):** [DAIR.AI](https://academy.dair.ai/blog/agents-md-evaluation) · [arxiviq](https://arxiviq.substack.com/p/evaluating-agentsmd-are-repository)

---

## Method note

The initial search cohort was discarded entirely: it came from SEO content farms
(codersera, limy.ai, mqlmagnet, betterclaw, morphllm, agentailor, digitalapplied)
and one AI-generated summary contradicted itself within four lines about whether
Claude Code reads `AGENTS.md`. Every claim above is re-sourced from a primary
document or a study with methodology.
