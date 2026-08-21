# Codex — Repository Intelligence Graph (Living Plan)

> A standalone project for building a repository intelligence layer between a Git repository and AI/LLM systems.
>
> **Codex is independent of ARCF and Veyra.**
>
> This document is the resumable reference plan for Codex. The project should **replicate established ecosystem capabilities before inventing new mechanisms**. Only after the replication baseline is complete should Codex investigate gaps and differentiated capabilities.

**Status:** RESEARCH / EXPERIMENTAL — architecture and implementation not yet started under this plan.

**Primary objective:**

```text
Git Repository
      ↓
Repository Intelligence Layer
      ↓
Evidence-backed Graph
      ↓
Graph / Context Retrieval
      ↓
LLM
```

Codex's purpose is to convert a raw repository into a deterministic, queryable representation of its structure, relationships, dependencies, runtime observations, and history so that humans and LLMs do not have to reconstruct repository architecture from raw source alone.

---

## 1. Core Principle

Codex will follow a **replicate → validate → identify gaps → extend** strategy.

It will NOT begin by creating a new parser, new graph schema, new visualization model, or new LLM architecture when an established ecosystem already provides an equivalent capability.

The working principle is:

```text
Existing ecosystem capability
          ↓
Reuse / integrate / reproduce
          ↓
Validate against real repositories
          ↓
Document what is still missing
          ↓
Build only the missing capability
```

The project should therefore avoid:

* rebuilding mature code-indexing infrastructure unnecessarily;
* inventing a proprietary graph schema before understanding existing standards;
* using an LLM to infer relationships that deterministic tooling can establish;
* claiming novelty for capabilities already demonstrated by Sourcegraph, RepoGraph, CodeSee, SCIP, or related systems;
* mixing Codex architecture with ARCF/Veyra architecture.

---

# 2. Problem Codex Is Solving

A raw Git repository is difficult for both humans and LLMs to understand at repository scale.

The LLM must otherwise perform several tasks itself:

```text
Locate symbols
      ↓
Understand files
      ↓
Find references
      ↓
Find implementations
      ↓
Trace calls
      ↓
Understand inheritance
      ↓
Identify dependencies
      ↓
Reconstruct architecture
      ↓
Trace execution
      ↓
Inspect history
      ↓
Reason about the result
```

Codex proposes moving the deterministic portions of that work into a repository intelligence layer.

The LLM should therefore receive:

```text
Question
   ↓
Codex graph/context query
   ↓
Verified repository evidence
   ↓
Relevant source + relationships + provenance
   ↓
LLM reasoning
```

The goal is not to eliminate the LLM.

The goal is to ensure the LLM spends its capability on **interpretation, explanation and reasoning**, rather than repeatedly reconstructing repository structure.

---

# 3. Existing Ecosystems to Replicate First

Codex will explicitly study and reproduce the relevant capabilities of existing systems before designing new ones.

## 3.1 Sourcegraph Code Intelligence / Code Graph

Sourcegraph already provides compiler-accurate code navigation concepts including definitions, references and implementations, and its Code Graph is used by Cody to retrieve structurally relevant context for LLM responses.

Sourcegraph's Code Graph is therefore the primary reference for:

* symbol indexing;
* definitions;
* references;
* implementations;
* inheritance relationships;
* repository navigation;
* graph-assisted context retrieval;
* LLM context selection.

Sourcegraph documents Code Graph as a structural representation of how code elements are interconnected and used.

**Codex decision:**
Do not recreate this functionality conceptually until the existing approach has been reproduced and measured.

---

## 3.2 SCIP — Code Intelligence Protocol

SCIP provides a language-agnostic indexing protocol for code navigation.

It already supports indexers across languages including:

* C/C++;
* C#;
* Dart;
* Go;
* Java;
* Kotlin;
* Scala;
* PHP;
* Python;
* Ruby;
* Rust;
* TypeScript;
* JavaScript.

SCIP is therefore the preferred candidate for Codex's initial cross-language code-index foundation rather than inventing an incompatible proprietary representation.

Codex should investigate:

```text
Repository
    ↓
Existing SCIP indexer
    ↓
SCIP index
    ↓
Codex graph representation
```

before implementing custom language analyzers.

---

## 3.3 Tree-sitter / Syntax-Level Parsing

Tree-sitter provides incremental parsing and concrete syntax trees across many languages. It is useful where Codex requires syntax-level information that existing semantic indexes do not expose.

Codex should therefore use Tree-sitter where appropriate rather than building language parsers from scratch.

Potential role:

```text
SCIP / compiler intelligence
        +
Tree-sitter syntax structure
        ↓
Codex normalized repository model
```

---

## 3.4 RepoGraph

RepoGraph demonstrates the repository-level code-graph approach for AI software engineering and uses a repository-wide graph as navigation/guidance for AI systems. Its published work reports improvements when integrated into multiple software-engineering systems.

Codex should reproduce the core idea:

```text
Repository
    ↓
Repository-level graph
    ↓
Graph-guided context
    ↓
AI/LLM
```

before attempting a novel graph-to-LLM mechanism.

---

## 3.5 Graph-Integrated LLM Approaches

Code Graph Model (CGM) represents a more advanced direction where repository structural dependencies are integrated more directly into LLM processing.

This should be treated as a **later reference architecture**, not the first implementation.

Codex first needs to establish whether a conventional:

```text
Graph
  ↓
Graph query
  ↓
Relevant context
  ↓
LLM
```

architecture already provides sufficient value.

Only then should graph-integrated model architectures be evaluated.

---

## 3.6 Visual Repository Graphs

CodeSee demonstrates a different but relevant direction: visual semantic flow representations intended to help humans understand what a project does. Its current implementation uses AI-generated semantic feature/flow information rather than being limited to traditional call or import graphs.

Codex should replicate the useful visual interaction patterns while maintaining a stricter evidence model:

```text
Node
Edge
Relationship type
Evidence source
Source location
Resolution status
```

Codex should not assume that AI-generated visual relationships are equivalent to compiler/static-analysis evidence.

---

# 4. Codex Evidence Model

Codex's central artifact is an **Evidence Graph**.

Every graph element should have provenance.

Example:

```text
authenticate()
      │
      │ CALLS
      ▼
_clean_credentials()
```

Evidence:

```text
source      = static-analysis
resolver    = SCIP/compiler/indexer
location    = file.py:42
verified    = true
```

External:

```text
authenticate()
      │
      │ CALLS
      ▼
[UNRESOLVED EXTERNAL]
```

Evidence:

```text
source      = static-analysis
resolution  = unresolved
verified    = relationship exists
target      = unknown
```

Runtime:

```text
authenticate()
      │
      │ OBSERVED_CALL
      ▼
OAuthClient.authenticate()
```

Evidence:

```text
source      = runtime
execution   = test_123
timestamp   = ...
```

Git:

```text
authenticate()
      │
      │ MODIFIED_BY
      ▼
commit abc123
```

Evidence:

```text
source      = git
commit      = abc123
timestamp   = ...
```

---

# 5. Relationship Vocabulary

The initial graph should use established concepts wherever possible.

Core structural relationships:

```text
CONTAINS
DEFINES
REFERENCES
CALLS
INHERITS
IMPLEMENTS
IMPORTS
DEPENDS_ON
```

Additional evidence relationships:

```text
OBSERVED_CALL
OBSERVED_EXECUTION
MODIFIED_BY
INTRODUCED_BY
DELETED_BY
RENAMED_BY
CO_CHANGED_WITH
```

External boundaries:

```text
EXTERNAL_LIBRARY
EXTERNAL_API
EXTERNAL_SERVICE
UNRESOLVED_SYMBOL
UNRESOLVED_DISPATCH
```

The exact final schema should not be frozen until the existing ecosystem schemas and index formats have been compared.

---

# 6. Phase 0 — Ecosystem Inventory — FIRST

**Status: NOT STARTED**

Before writing Codex implementation code, produce a capability matrix covering:

| Capability             | Sourcegraph | SCIP | RepoGraph | CodeSee | Other | Codex status |
| ---------------------- | ----------- | ---- | --------- | ------- | ----- | ------------ |
| Symbol extraction      |             |      |           |         |       |              |
| Definitions            |             |      |           |         |       |              |
| References             |             |      |           |         |       |              |
| Implementations        |             |      |           |         |       |              |
| Inheritance            |             |      |           |         |       |              |
| Call relationships     |             |      |           |         |       |              |
| Import relationships   |             |      |           |         |       |              |
| External dependencies  |             |      |           |         |       |              |
| Visualization          |             |      |           |         |       |              |
| Graph retrieval        |             |      |           |         |       |              |
| LLM context generation |             |      |           |         |       |              |
| Runtime tracing        |             |      |           |         |       |              |
| Git history            |             |      |           |         |       |              |
| Incremental updates    |             |      |           |         |       |              |
| Provenance             |             |      |           |         |       |              |
| Unresolved/open edges  |             |      |           |         |       |              |

**Exit criterion:**

No major Codex feature is implemented until the team can answer:

> "Does an existing ecosystem already provide this?"

---

# 7. Phase 1 — Replicate Static Code Intelligence

**Status: NOT STARTED**

Objective:

Produce a repository graph using existing code-intelligence infrastructure.

Preferred experiment:

```text
Git Repository
      ↓
SCIP / existing language indexer
      ↓
Definitions / references / implementations
      ↓
Codex normalized graph
```

Test repositories should include multiple languages.

Initial language set:

```text
Python
Java
JavaScript
TypeScript
Go
```

No custom language parser should be written unless an existing ecosystem cannot provide the required information.

### Required graph nodes

```text
Repository
Module
File
Class
Interface
Function
Method
Variable
Parameter
External symbol
```

### Required relationships

```text
DEFINES
CONTAINS
REFERENCES
CALLS
INHERITS
IMPLEMENTS
IMPORTS
```

### Validation

For each repository:

* count indexed symbols;
* compare definitions;
* compare references;
* compare implementations;
* measure unresolved relationships;
* inspect representative call chains;
* record false-positive and false-negative relationships.

---

# 8. Phase 2 — Replicate Repository-Level Graph Navigation

**Status: NOT STARTED**

Objective:

Reproduce the repository-wide graph navigation concept demonstrated by RepoGraph and Sourcegraph.

Example:

```text
User query:
"Where is authentication implemented?"
```

Graph traversal:

```text
authentication
     ↓
symbol candidates
     ↓
implementations
     ↓
callers
     ↓
dependencies
```

The output should be a graph-derived context package:

```text
Target symbols
Relevant neighbors
Relationship paths
Source locations
Evidence
```

This phase should answer:

> Can graph traversal reduce repository search effort without requiring the LLM to reconstruct the relationships?

---

# 9. Phase 3 — Replicate LLM Context Integration

**Status: NOT STARTED**

Objective:

Build the simplest possible:

```text
User question
      ↓
Graph retrieval
      ↓
Relevant repository evidence
      ↓
LLM
```

No graph-integrated neural architecture yet.

Compare:

```text
Baseline A:
Raw text / normal retrieval → LLM

Baseline B:
Graph retrieval → LLM

Baseline C:
Graph + source retrieval → LLM
```

Measure:

* context tokens;
* irrelevant context;
* answer correctness;
* repository navigation steps;
* latency;
* LLM calls;
* context size;
* hallucinated relationships.

Sourcegraph's current architecture is a useful reference because Cody combines keyword/search context with Code Graph information when gathering context for an LLM.

---

# 10. Phase 4 — Replicate Visual Repository Representation

**Status: NOT STARTED**

Objective:

Automatically generate a visual representation immediately after repository ingestion.

Initial views:

### Repository hierarchy

```text
Repository
 ├── Package
 │    ├── Class
 │    │    ├── Method
 │    │    └── Method
 │    └── Class
 └── Package
```

### Call graph

```text
A
 ↓
B
 ↓
C
```

### Inheritance graph

```text
Base
 ▲
 ├── ChildA
 └── ChildB
```

### Dependency graph

```text
Application
 ├── Internal module
 ├── External library
 └── External API
```

### Combined graph

Allow users to switch projections instead of rendering every relationship simultaneously.

The visualization should always expose relationship provenance.

---

# 11. Phase 5 — External / Open Connections

**Status: NOT STARTED**

This phase implements one of Codex's explicit product requirements.

When a relationship is established but its destination cannot be resolved inside the repository:

```text
Application
     │
     ▼
requests.get()
     │
     ▼
[EXTERNAL LIBRARY]
```

or:

```text
Service
     │
     ▼
POST /payments
     │
     ▼
[EXTERNAL API]
```

or:

```text
obj.authenticate()
     │
     ▼
[UNRESOLVED DISPATCH]
```

Codex must represent the boundary rather than inventing the destination.

This distinction becomes a first-class graph state:

```text
RESOLVED
UNRESOLVED
EXTERNAL
RUNTIME_ONLY
STATIC_ONLY
```

---

# 12. Phase 6 — Incremental Repository Updates

**Status: NOT STARTED**

Objective:

The graph should not need to be rebuilt from scratch after every source change.

Investigate existing incremental mechanisms first.

Tree-sitter already supports incremental parsing and efficient syntax-tree updates.

Desired model:

```text
Initial clone
     ↓
Full index
     ↓
Graph v1
     ↓
Developer changes file
     ↓
Incremental analysis
     ↓
Graph v2
```

Only affected nodes and relationships should be recomputed where the underlying tools support it.

---

# 13. Phase 7 — Runtime Intelligence

**Status: NOT STARTED — HIGHER RISK**

Objective:

Enrich static relationships with actual runtime observations.

Desired model:

```text
STATIC GRAPH
A ──CALLS──> B

RUNTIME
Test_001
A ──OBSERVED_CALL──> B
```

Runtime evidence should **never silently replace static evidence**.

Instead:

```text
Relationship
    ├── STATIC evidence
    └── RUNTIME evidence
```

Potential runtime information:

```text
Executed function
Observed call
Execution path
Branch taken
External API invoked
Database interaction
Exception path
Timing
```

This phase should begin with instrumentation capabilities already available in the target language ecosystem rather than implementing a universal tracing engine.

---

# 14. Phase 8 — Git History Intelligence

**Status: NOT STARTED**

Objective:

Add repository evolution as another evidence dimension.

Extract:

```text
Commit
Parent commit
Changed file
Changed symbol
Author
Timestamp
Diff
Rename
Deletion
Addition
```

Derive deterministic historical relationships where justified:

```text
MODIFIED_BY
INTRODUCED_BY
DELETED_BY
RENAMED_BY
CO_CHANGED_WITH
```

Example:

```text
AuthenticationService
      │
      ├── INTRODUCED_BY → abc123
      ├── MODIFIED_BY → def456
      ├── MODIFIED_BY → ghi789
      └── CO_CHANGED_WITH → OAuthClient
```

The LLM can then reason over historical evidence rather than searching Git history itself.

Important constraint:

Git evidence does not automatically establish developer intent.

Codex must distinguish:

```text
FACT:
"These files changed together."

from:

INFERENCE:
"These files were changed together because of authentication refactoring."
```

The second is an LLM interpretation, not a graph fact.

---

# 15. Phase 9 — Unified Repository Intelligence Graph

**Status: NOT STARTED**

After static, visualization, runtime and Git capabilities have individually been reproduced:

```text
                 REPOSITORY
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
    STATIC        RUNTIME         GIT
   EVIDENCE       EVIDENCE      HISTORY
       │             │             │
       └─────────────┼─────────────┘
                     ▼
          REPOSITORY INTELLIGENCE
                   GRAPH
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
   Visualizer     Graph Query     LLM Context
```

This becomes the first real Codex baseline.

---

# 16. Phase 10 — Gap Analysis

**Status: NOT STARTED**

Only after Phases 0–9 are working should Codex ask:

> What is still missing from existing ecosystems?

Potential gap categories to investigate:

### A. Unified evidence provenance

Can Codex expose:

```text
Why does this edge exist?
Which analyzer produced it?
Which source line proves it?
Was it statically resolved?
Was it runtime observed?
Which commit introduced it?
```

as one unified model?

### B. Static + runtime reconciliation

Can Codex represent:

```text
Static says:
A → B

Runtime says:
A → C
```

without destroying either fact?

### C. Open-world boundaries

Can external libraries, APIs, services and unresolved dispatches be represented naturally rather than treated as missing graph data?

### D. Historical graph

Can structural graph and Git evolution be queried together?

Example:

> "Show me the current authentication flow and how it changed over the last six months."

### E. Living graph

Can the graph update automatically after:

```text
edit
build
test
run
commit
merge
```

without requiring a complete re-index?

### F. Evidence-aware LLM context

Can Codex give the LLM:

```text
facts
+
relationships
+
source
+
runtime observations
+
history
+
provenance
```

while explicitly separating facts from inference?

### G. Multi-view graph

Can one underlying graph generate:

```text
Architecture view
Call-flow view
Dependency view
Runtime view
Inheritance view
Git evolution view
LLM context view
```

without maintaining independent representations?

---

# 17. Phase 11 — Gap Experiments

**Status: NOT STARTED**

Each identified gap becomes an independent experiment.

No feature should be implemented merely because it sounds useful.

For every proposed gap:

```text
Existing capability
       ↓
Observed limitation
       ↓
Concrete hypothesis
       ↓
Minimal implementation
       ↓
Before / after measurement
       ↓
Keep / reject
```

This prevents Codex from becoming another large speculative architecture.

---

# 18. Phase 12 — Codex Differentiation

**Status: NOT STARTED**

Only mechanisms that survive the gap experiments become Codex-specific capabilities.

The final question is:

> What does Codex provide that existing code intelligence + graph + visualization + AI systems do not already provide adequately?

Potential differentiation must be demonstrated experimentally rather than assumed.

---

# 19. Non-Goals

Codex will NOT initially attempt to:

* train a new LLM;
* create a new foundation model;
* invent a new universal parser;
* replace Sourcegraph/SCIP/Tree-sitter without justification;
* create an LLM-generated graph when deterministic evidence is available;
* infer undocumented architecture as fact;
* claim complete call resolution where static analysis cannot resolve a call;
* merge runtime observations into static truth without provenance;
* treat Git co-change as proof of semantic dependency;
* reproduce every ecosystem feature simultaneously.

---

# 20. Validation Philosophy

Codex will use real repositories rather than synthetic toy projects wherever possible.

Each phase requires:

```text
Capability
+
Known ground truth
+
Real repository
+
Measured result
+
Failure analysis
```

For graph relationships:

```text
Precision
Recall
Unresolved rate
False-positive rate
False-negative rate
```

For LLM integration:

```text
Answer accuracy
Context tokens
Relevant-context ratio
Latency
LLM calls
Hallucination rate
```

For visualization:

```text
Node coverage
Edge coverage
Relationship correctness
Navigation usefulness
Rendering performance
```

For runtime:

```text
Observed-path coverage
Static/runtime agreement
Unresolved-path rate
Instrumentation overhead
```

For Git history:

```text
Symbol-history accuracy
Rename tracking
Change attribution
Historical relationship accuracy
```

---

# 21. Project Milestones

## M0 — Ecosystem Understanding

**Goal:** Know what already exists.

Deliverable:

```text
Codex Ecosystem Capability Matrix
```

---

## M1 — Static Intelligence Baseline

**Goal:** Existing indexers → repository graph.

Deliverable:

```text
Multi-language structural graph
```

---

## M2 — Graph Navigation

**Goal:** Repository-level graph traversal.

Deliverable:

```text
Question → graph → relevant repository context
```

---

## M3 — LLM Context Baseline

**Goal:** Graph-assisted LLM context.

Deliverable:

```text
Question → graph context → LLM
```

---

## M4 — Visual Repository Intelligence

**Goal:** Automatically generated repository graph views.

Deliverable:

```text
Clone repository
      ↓
Graph generated
      ↓
Visual representation
```

---

## M5 — External/Open Boundaries

**Goal:** Correctly represent unresolved and external relationships.

Deliverable:

```text
Internal ──→ External
Internal ──→ Unresolved
```

---

## M6 — Incremental / Living Graph

**Goal:** Keep graph synchronized with source changes.

Deliverable:

```text
Code change → graph update
```

---

## M7 — Runtime Intelligence

**Goal:** Add actual execution evidence.

Deliverable:

```text
Static graph + Runtime graph
```

---

## M8 — Git Intelligence

**Goal:** Add evolution/history.

Deliverable:

```text
Current architecture + historical architecture
```

---

## M9 — Unified Evidence Graph

**Goal:** Combine all evidence dimensions.

Deliverable:

```text
Static
Runtime
Git
External
Provenance
        ↓
Unified Evidence Graph
```

---

## M10 — Gap Discovery

**Goal:** Identify capabilities not adequately solved by existing ecosystems.

Deliverable:

```text
Codex Gap Report
```

---

## M11 — Differentiated Capabilities

**Goal:** Build only experimentally justified gaps.

Deliverable:

```text
Codex-specific innovations
```

---

## M12 — Final Evaluation

**Goal:** Determine whether Codex provides measurable value beyond existing approaches.

Compare:

```text
Raw repository → LLM
Existing code intelligence → LLM
Existing graph → LLM
Codex → LLM
```

Measure:

```text
Context efficiency
Answer accuracy
Repository understanding
Navigation effort
Hallucination rate
Latency
Cost
Runtime usefulness
Historical understanding
```

---

# 22. Target Architecture

The intended final architecture is:

```text
                         GIT REPOSITORY
                               │
                               ▼
                  ┌────────────────────────┐
                  │ Existing Ecosystem     │
                  │ Indexers / Parsers     │
                  │ SCIP / Tree-sitter     │
                  └────────────┬───────────┘
                               │
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
              STRUCTURE     RUNTIME        GIT
               EVIDENCE     EVIDENCE      HISTORY
                  │            │            │
                  └────────────┼────────────┘
                               ▼
                  ┌────────────────────────┐
                  │ CODEX EVIDENCE GRAPH   │
                  │                        │
                  │ Nodes                  │
                  │ Relationships          │
                  │ Provenance              │
                  │ Resolution status       │
                  │ Source locations        │
                  │ Runtime observations    │
                  │ Historical evidence     │
                  └────────────┬───────────┘
                               │
               ┌───────────────┼────────────────┐
               ▼               ▼                ▼
          VISUALIZATION    GRAPH QUERY       LLM CONTEXT
               │               │                │
               ▼               └────────┬───────┘
          Human understanding            ▼
                                      LLM
                                        │
                                        ▼
                              Reasoning / Explanation
```

---

# 23. Core Architectural Rule

Codex should maintain a strict boundary:

```text
DETERMINISTIC LAYER
-------------------
What exists?
Where is it?
What connects to what?
What implements what?
What was executed?
What changed?
What evidence proves it?
              ↓
LLM LAYER
---------
What does it mean?
Why is it designed this way?
What is the likely intent?
How should it be explained?
What could be improved?
```

The LLM may reason **from evidence**.

It must not silently become the source of structural truth.

---

# 24. Current Decision

The previous retrieval-focused Codex experiment is **not the main project direction anymore**.

It may be retained as an isolated experiment/reference because it demonstrated that structural facts can influence retrieval, but it should not dictate the new architecture.

The new Codex strategy is:

```text
DO NOT:
Build a new repository intelligence system from scratch.

DO:
1. Study existing ecosystems.
2. Reuse their mature components.
3. Reproduce their capabilities.
4. Validate them on real repositories.
5. Combine compatible capabilities.
6. Identify what remains unsolved.
7. Build only those gaps.
```

---

# 25. Immediate Next Step

**Do not implement Codex yet.**

The next action is **M0 — Ecosystem Capability Matrix**.

The first concrete research set should be:

```text
Sourcegraph Code Graph
SCIP
Tree-sitter
RepoGraph
CodeSee
Graph-RAG approaches
Graph-integrated LLM approaches
Runtime tracing ecosystems
Git history / code evolution tools
```

For each, determine:

```text
What it already solves
How it solves it
What can be reused
What can be reproduced
What it does not solve
What evidence supports its capability
```

Only after that matrix is complete should Codex architecture be frozen.

---

## Guiding statement

> **Codex is not an attempt to reinvent repository intelligence. Codex first assembles and validates the best existing repository-intelligence capabilities into one evidence-backed graph. Its actual innovation begins only at the boundaries where those ecosystems leave measurable gaps.**
