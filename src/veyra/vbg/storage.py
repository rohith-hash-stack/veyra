"""
PLAN.md Phase 1.2 -- VBG storage layer.

Storage decision (PLAN.md D3): SQLite, event-sourced / SCD-Type-2. Nodes,
edges, and repository records are never updated or deleted in place -- every
write is a brand new row, keyed by its natural identity plus
repository_version. "Historical records cannot be silently overwritten" is
enforced structurally, not just by convention: VBGStore exposes no update or
delete method for any entity, only insert + read. Conflicting writes for the
same natural key (e.g. two analyses disagreeing about the same node at the
same commit) are retained side by side as history, which is also how
"conflicts are representable" is satisfied at the storage level.

Graph traversal at a given commit is a plain filtered query for now
(recursive-CTE / in-memory traversal is Phase 2.3/2.4's concern, once there
is an actual structural graph to traverse).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from veyra.acquisition import AcquisitionStatus, RepositoryInfo
from veyra.audit import AuditRecord

from .evidence import Evidence, EvidenceType, Provenance
from .execution import ExecutionEnvironment
from .models import Edge, Node, RelationshipType, RepositoryRecord, VerificationState
from .questions import Answer, AnswerStatus, Question, QuestionCategory
from .safety import Capability, ClassificationResult, RiskLevel, SafetyClass
from .scenarios import Scenario, ScenarioUnexecutableReason

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    repository_version TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    language TEXT,
    source_location TEXT,
    lexical_representation TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_entity_version
    ON nodes (entity_id, repository_version);

CREATE TABLE IF NOT EXISTS edges (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    repository_version TEXT NOT NULL,
    status TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_key_version
    ON edges (source_id, target_id, relationship_type, repository_version);

CREATE TABLE IF NOT EXISTS repositories (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    language_counts TEXT NOT NULL,
    repository_size_bytes INTEGER NOT NULL,
    clone_duration_seconds REAL NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_repositories_source_commit
    ON repositories (source, commit_sha);

CREATE TABLE IF NOT EXISTS evidence (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    repository_version TEXT NOT NULL,
    provenance_producer TEXT NOT NULL,
    provenance_method TEXT NOT NULL,
    provenance_recorded_at TEXT NOT NULL,
    location TEXT,
    detail TEXT,
    scenario_id TEXT,
    environment_id TEXT,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_subject_version
    ON evidence (subject_id, repository_version);

CREATE TABLE IF NOT EXISTS audit_events (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    success INTEGER NOT NULL,
    repository_commit TEXT,
    error_reason TEXT,
    input_size INTEGER,
    output_size INTEGER,
    memory_bytes INTEGER,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_phase_commit
    ON audit_events (phase, repository_commit);

CREATE TABLE IF NOT EXISTS questions (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    category TEXT NOT NULL,
    template_key TEXT NOT NULL,
    text TEXT NOT NULL,
    entity_ids TEXT NOT NULL,
    repository_version TEXT NOT NULL,
    provenance TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_version
    ON questions (repository_version, question_id);

CREATE TABLE IF NOT EXISTS answers (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    status TEXT NOT NULL,
    entity_ids TEXT NOT NULL,
    value TEXT NOT NULL,
    repository_version TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answers_question
    ON answers (question_id, repository_version);

CREATE TABLE IF NOT EXISTS classifications (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    classification TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    capabilities_detected TEXT NOT NULL,
    matched_rules TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL,
    repository_commit TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_classifications_target_commit
    ON classifications (target, repository_commit);

CREATE TABLE IF NOT EXISTS execution_environments (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment_id TEXT NOT NULL,
    backend TEXT NOT NULL,
    image TEXT NOT NULL,
    network_enabled INTEGER NOT NULL,
    memory_limit_mb INTEGER NOT NULL,
    cpu_limit REAL NOT NULL,
    timeout_seconds REAL NOT NULL,
    non_privileged INTEGER NOT NULL,
    read_only_filesystem INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_environments_id
    ON execution_environments (environment_id);

CREATE TABLE IF NOT EXISTS scenarios (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    description TEXT NOT NULL,
    required_inputs TEXT NOT NULL,
    dependencies TEXT NOT NULL,
    expected_observable_points TEXT NOT NULL,
    safety_class TEXT NOT NULL,
    executable INTEGER NOT NULL,
    unexecutable_reason TEXT,
    detail TEXT,
    repository_version TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenarios_version
    ON scenarios (repository_version, scenario_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_node(row: sqlite3.Row) -> Node:
    return Node(
        entity_id=row["entity_id"],
        type=row["type"],
        name=row["name"],
        repository_version=row["repository_version"],
        language=row["language"],
        source_location=row["source_location"],
        lexical_representation=row["lexical_representation"],
        occurrence_count=row["occurrence_count"],
        status=VerificationState(row["status"]),
    )


def _row_to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        source_id=row["source_id"],
        target_id=row["target_id"],
        relationship_type=RelationshipType(row["relationship_type"]),
        repository_version=row["repository_version"],
        status=VerificationState(row["status"]),
    )


def _row_to_evidence(row: sqlite3.Row) -> Evidence:
    return Evidence(
        subject_id=row["subject_id"],
        evidence_type=EvidenceType(row["evidence_type"]),
        repository_version=row["repository_version"],
        provenance=Provenance(
            producer=row["provenance_producer"],
            method=row["provenance_method"],
            recorded_at=row["provenance_recorded_at"],
        ),
        location=row["location"],
        detail=row["detail"],
        scenario_id=row["scenario_id"],
        environment_id=row["environment_id"],
    )


def _row_to_audit_record(row: sqlite3.Row) -> AuditRecord:
    return AuditRecord(
        phase=row["phase"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_seconds=row["duration_seconds"],
        success=bool(row["success"]),
        repository_commit=row["repository_commit"],
        error_reason=row["error_reason"],
        input_size=row["input_size"],
        output_size=row["output_size"],
        memory_bytes=row["memory_bytes"],
    )


def _row_to_question(row: sqlite3.Row) -> Question:
    return Question(
        question_id=row["question_id"],
        category=QuestionCategory(row["category"]),
        template_key=row["template_key"],
        text=row["text"],
        entity_ids=tuple(json.loads(row["entity_ids"])),
        repository_version=row["repository_version"],
        provenance=row["provenance"],
    )


def _row_to_answer(row: sqlite3.Row) -> Answer:
    return Answer(
        question_id=row["question_id"],
        status=AnswerStatus(row["status"]),
        entity_ids=tuple(json.loads(row["entity_ids"])),
        value=row["value"],
        repository_version=row["repository_version"],
    )


def _row_to_classification_result(row: sqlite3.Row) -> ClassificationResult:
    return ClassificationResult(
        target=row["target"],
        classification=SafetyClass(row["classification"]),
        risk_level=RiskLevel(row["risk_level"]),
        capabilities_detected=tuple(Capability(v) for v in json.loads(row["capabilities_detected"])),
        matched_rules=tuple(json.loads(row["matched_rules"])),
        reason=row["reason"],
        evidence=tuple(json.loads(row["evidence"])),
        repository_commit=row["repository_commit"],
        policy_version=row["policy_version"],
    )


def _row_to_execution_environment(row: sqlite3.Row) -> ExecutionEnvironment:
    return ExecutionEnvironment(
        environment_id=row["environment_id"],
        backend=row["backend"],
        image=row["image"],
        network_enabled=bool(row["network_enabled"]),
        memory_limit_mb=row["memory_limit_mb"],
        cpu_limit=row["cpu_limit"],
        timeout_seconds=row["timeout_seconds"],
        non_privileged=bool(row["non_privileged"]),
        read_only_filesystem=bool(row["read_only_filesystem"]),
    )


def _row_to_scenario(row: sqlite3.Row) -> Scenario:
    return Scenario(
        scenario_id=row["scenario_id"],
        target_entity_id=row["target_entity_id"],
        description=row["description"],
        required_inputs=tuple(json.loads(row["required_inputs"])),
        dependencies=tuple(json.loads(row["dependencies"])),
        expected_observable_points=tuple(json.loads(row["expected_observable_points"])),
        safety_class=SafetyClass(row["safety_class"]),
        executable=bool(row["executable"]),
        repository_version=row["repository_version"],
        unexecutable_reason=(
            ScenarioUnexecutableReason(row["unexecutable_reason"])
            if row["unexecutable_reason"] is not None
            else None
        ),
        detail=row["detail"],
    )


def _row_to_repository_record(row: sqlite3.Row) -> RepositoryRecord:
    return RepositoryRecord(
        source=row["source"],
        commit_sha=row["commit_sha"],
        file_count=row["file_count"],
        language_counts=json.loads(row["language_counts"]),
        repository_size_bytes=row["repository_size_bytes"],
        clone_duration_seconds=row["clone_duration_seconds"],
        recorded_at=row["recorded_at"],
    )


class VBGStore:
    """
    Append-only store for the canonical VBG. By design, no method on this
    class ever issues SQL UPDATE or DELETE -- that omission is the actual
    enforcement mechanism for "historical records cannot be silently
    overwritten" (PLAN.md Phase 1.2), not just a documented convention.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- Nodes ---------------------------------------------------------

    def insert_node(self, node: Node) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    entity_id, repository_version, type, name, language,
                    source_location, lexical_representation, occurrence_count,
                    status, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.entity_id,
                    node.repository_version,
                    node.type,
                    node.name,
                    node.language,
                    node.source_location,
                    node.lexical_representation,
                    node.occurrence_count,
                    node.status.value,
                    _now(),
                ),
            )
            conn.commit()

    def get_node_history(self, entity_id: str, repository_version: str) -> list[Node]:
        """All rows ever recorded for this (entity_id, repository_version),
        oldest first. Never empty-then-overwritten -- every write ever made
        is present."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM nodes
                WHERE entity_id = ? AND repository_version = ?
                ORDER BY row_id ASC
                """,
                (entity_id, repository_version),
            ).fetchall()
        return [_row_to_node(row) for row in rows]

    def get_latest_node(self, entity_id: str, repository_version: str) -> Node | None:
        history = self.get_node_history(entity_id, repository_version)
        return history[-1] if history else None

    # -- Edges -----------------------------------------------------------

    def insert_edge(self, edge: Edge) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO edges (
                    source_id, target_id, relationship_type,
                    repository_version, status, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.source_id,
                    edge.target_id,
                    edge.relationship_type.value,
                    edge.repository_version,
                    edge.status.value,
                    _now(),
                ),
            )
            conn.commit()

    def get_edge_history(
        self,
        source_id: str,
        target_id: str,
        relationship_type: RelationshipType,
        repository_version: str,
    ) -> list[Edge]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM edges
                WHERE source_id = ? AND target_id = ?
                  AND relationship_type = ? AND repository_version = ?
                ORDER BY row_id ASC
                """,
                (source_id, target_id, relationship_type.value, repository_version),
            ).fetchall()
        return [_row_to_edge(row) for row in rows]

    def get_latest_edge(
        self,
        source_id: str,
        target_id: str,
        relationship_type: RelationshipType,
        repository_version: str,
    ) -> Edge | None:
        history = self.get_edge_history(source_id, target_id, relationship_type, repository_version)
        return history[-1] if history else None

    def get_outgoing_edges(self, source_id: str, repository_version: str) -> list[Edge]:
        """The current (most recently recorded) edge for every distinct
        (target_id, relationship_type) pair out of `source_id` at this
        commit -- the graph-traversal primitive Phase 2.4's Neighborhood
        Model is built on. Superseded/conflicting historical rows are not
        included here; use get_edge_history() for the full audit trail of a
        specific edge."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT e.* FROM edges e
                INNER JOIN (
                    SELECT target_id, relationship_type, MAX(row_id) AS max_row_id
                    FROM edges
                    WHERE source_id = ? AND repository_version = ?
                    GROUP BY target_id, relationship_type
                ) latest
                ON e.target_id = latest.target_id
                   AND e.relationship_type = latest.relationship_type
                   AND e.row_id = latest.max_row_id
                WHERE e.source_id = ? AND e.repository_version = ?
                """,
                (source_id, repository_version, source_id, repository_version),
            ).fetchall()
        return [_row_to_edge(row) for row in rows]

    def get_all_nodes(self, repository_version: str) -> list[Node]:
        """Current view: the latest row per distinct entity_id at this
        commit. Duplicate-symbol history (Phase 2.1) is still fully
        queryable via get_node_history() for anyone who needs it; bulk
        graph consumers like the Phase 2.5 question generator only need the
        current view."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT n.* FROM nodes n
                INNER JOIN (
                    SELECT entity_id, MAX(row_id) AS max_row_id
                    FROM nodes WHERE repository_version = ?
                    GROUP BY entity_id
                ) latest ON n.entity_id = latest.entity_id AND n.row_id = latest.max_row_id
                WHERE n.repository_version = ?
                """,
                (repository_version, repository_version),
            ).fetchall()
        return [_row_to_node(row) for row in rows]

    def get_all_edges(self, repository_version: str) -> list[Edge]:
        """Current view: the latest row per distinct
        (source_id, target_id, relationship_type) at this commit."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT e.* FROM edges e
                INNER JOIN (
                    SELECT source_id, target_id, relationship_type, MAX(row_id) AS max_row_id
                    FROM edges WHERE repository_version = ?
                    GROUP BY source_id, target_id, relationship_type
                ) latest ON e.source_id = latest.source_id AND e.target_id = latest.target_id
                         AND e.relationship_type = latest.relationship_type AND e.row_id = latest.max_row_id
                WHERE e.repository_version = ?
                """,
                (repository_version, repository_version),
            ).fetchall()
        return [_row_to_edge(row) for row in rows]

    def get_incoming_edges(self, target_id: str, repository_version: str) -> list[Edge]:
        """The current edge for every distinct (source_id, relationship_type)
        pair into `target_id` at this commit -- see get_outgoing_edges()."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT e.* FROM edges e
                INNER JOIN (
                    SELECT source_id, relationship_type, MAX(row_id) AS max_row_id
                    FROM edges
                    WHERE target_id = ? AND repository_version = ?
                    GROUP BY source_id, relationship_type
                ) latest
                ON e.source_id = latest.source_id
                   AND e.relationship_type = latest.relationship_type
                   AND e.row_id = latest.max_row_id
                WHERE e.target_id = ? AND e.repository_version = ?
                """,
                (target_id, repository_version, target_id, repository_version),
            ).fetchall()
        return [_row_to_edge(row) for row in rows]

    # -- Repository acquisition record -----------------------------------

    def record_repository(self, info: RepositoryInfo) -> None:
        """Persist a successful Phase 1.1 acquisition. Raises ValueError for
        a failed acquisition -- reuses RepositoryInfo.require_commit()'s
        guard, since a repository version is required to record anything."""
        commit_sha = info.require_commit()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO repositories (
                    source, commit_sha, file_count, language_counts,
                    repository_size_bytes, clone_duration_seconds, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    info.source,
                    commit_sha,
                    info.file_count,
                    json.dumps(info.language_counts, sort_keys=True),
                    info.repository_size_bytes,
                    info.clone_duration_seconds,
                    _now(),
                ),
            )
            conn.commit()

    def get_repository_history(self, source: str, commit_sha: str) -> list[RepositoryRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM repositories
                WHERE source = ? AND commit_sha = ?
                ORDER BY row_id ASC
                """,
                (source, commit_sha),
            ).fetchall()
        return [_row_to_repository_record(row) for row in rows]

    # -- Evidence ----------------------------------------------------------

    def insert_evidence(self, evidence: Evidence) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO evidence (
                    subject_id, evidence_type, repository_version,
                    provenance_producer, provenance_method, provenance_recorded_at,
                    location, detail, scenario_id, environment_id, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.subject_id,
                    evidence.evidence_type.value,
                    evidence.repository_version,
                    evidence.provenance.producer,
                    evidence.provenance.method,
                    evidence.provenance.recorded_at,
                    evidence.location,
                    evidence.detail,
                    evidence.scenario_id,
                    evidence.environment_id,
                    _now(),
                ),
            )
            conn.commit()

    def get_evidence_for_subject(self, subject_id: str, repository_version: str) -> list[Evidence]:
        """All evidence ever recorded for this subject at this commit, oldest
        first. Unlike nodes/edges, multiple evidence records for the same
        subject are not competing versions of one fact -- they are
        independent supporting observations (e.g. STATIC and RUNTIME
        evidence for the same edge) and are all expected to coexist."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM evidence
                WHERE subject_id = ? AND repository_version = ?
                ORDER BY row_id ASC
                """,
                (subject_id, repository_version),
            ).fetchall()
        return [_row_to_evidence(row) for row in rows]

    def has_evidence(self, subject_id: str, repository_version: str) -> bool:
        """Supports checking the acceptance criterion "every verified claim
        has evidence" -- callers assigning a verified status to a Node/Edge
        can confirm evidence exists for that subject first."""
        return len(self.get_evidence_for_subject(subject_id, repository_version)) > 0

    def count_evidence(self, repository_version: str, evidence_type: EvidenceType | None = None) -> int:
        """Aggregate count for audit reporting (Phase 2.8's "static evidence
        created") -- unlike get_evidence_for_subject, this isn't scoped to
        one subject."""
        with closing(self._connect()) as conn:
            if evidence_type is None:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM evidence WHERE repository_version = ?",
                    (repository_version,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM evidence WHERE repository_version = ? AND evidence_type = ?",
                    (repository_version, evidence_type.value),
                ).fetchone()
        return int(row["c"])

    def get_all_evidence(
        self, repository_version: str, evidence_type: EvidenceType | None = None
    ) -> list[Evidence]:
        """Every evidence row at this commit (optionally filtered to one
        EvidenceType), not scoped to a single subject -- unlike Node/Edge's
        get_all_*, this is NOT a "latest per key" current view, since
        multiple evidence rows for the same subject are independent
        coexisting observations, not competing versions (see
        get_evidence_for_subject). Backs Phase 3.7's reconciliation (which
        needs every RUNTIME edge/node observation at once) and Phase 3.9's
        runtime audit."""
        with closing(self._connect()) as conn:
            if evidence_type is None:
                rows = conn.execute(
                    "SELECT * FROM evidence WHERE repository_version = ? ORDER BY row_id ASC",
                    (repository_version,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evidence WHERE repository_version = ? AND evidence_type = ? ORDER BY row_id ASC",
                    (repository_version, evidence_type.value),
                ).fetchall()
        return [_row_to_evidence(row) for row in rows]

    # -- Audit (Phase 1.5) --------------------------------------------------

    def insert_audit_record(self, record: AuditRecord) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    phase, started_at, ended_at, duration_seconds, success,
                    repository_commit, error_reason, input_size, output_size,
                    memory_bytes, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.phase,
                    record.started_at,
                    record.ended_at,
                    record.duration_seconds,
                    int(record.success),
                    record.repository_commit,
                    record.error_reason,
                    record.input_size,
                    record.output_size,
                    record.memory_bytes,
                    _now(),
                ),
            )
            conn.commit()

    def get_audit_history(
        self, phase: str, repository_commit: str | None = None
    ) -> list[AuditRecord]:
        with closing(self._connect()) as conn:
            if repository_commit is None:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE phase = ? ORDER BY row_id ASC",
                    (phase,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM audit_events
                    WHERE phase = ? AND repository_commit = ?
                    ORDER BY row_id ASC
                    """,
                    (phase, repository_commit),
                ).fetchall()
        return [_row_to_audit_record(row) for row in rows]

    # -- Questions & Answers (Phase 2.5/2.6) --------------------------------

    def insert_question(self, question: Question) -> None:
        """Makes "unanswered questions remain queryable" (Phase 2.7) true in
        practice: a Question exists here the moment it's generated, whether
        or not it's ever answered."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO questions (
                    question_id, category, template_key, text, entity_ids,
                    repository_version, provenance, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question.question_id,
                    question.category.value,
                    question.template_key,
                    question.text,
                    json.dumps(list(question.entity_ids)),
                    question.repository_version,
                    question.provenance,
                    _now(),
                ),
            )
            conn.commit()

    def get_questions(self, repository_version: str) -> list[Question]:
        """Current view: latest row per distinct question_id at this commit."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT q.* FROM questions q
                INNER JOIN (
                    SELECT question_id, MAX(row_id) AS max_row_id
                    FROM questions WHERE repository_version = ?
                    GROUP BY question_id
                ) latest ON q.question_id = latest.question_id AND q.row_id = latest.max_row_id
                WHERE q.repository_version = ?
                ORDER BY q.row_id ASC
                """,
                (repository_version, repository_version),
            ).fetchall()
        return [_row_to_question(row) for row in rows]

    def insert_answer(self, answer: Answer) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO answers (
                    question_id, status, entity_ids, value,
                    repository_version, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    answer.question_id,
                    answer.status.value,
                    json.dumps(list(answer.entity_ids)),
                    answer.value,
                    answer.repository_version,
                    _now(),
                ),
            )
            conn.commit()

    def get_answer_history(self, question_id: str, repository_version: str) -> list[Answer]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM answers
                WHERE question_id = ? AND repository_version = ?
                ORDER BY row_id ASC
                """,
                (question_id, repository_version),
            ).fetchall()
        return [_row_to_answer(row) for row in rows]

    def get_latest_answer(self, question_id: str, repository_version: str) -> Answer | None:
        history = self.get_answer_history(question_id, repository_version)
        return history[-1] if history else None

    # -- Safety classification (Phase 3.1) -----------------------------------

    def insert_classification(self, result: ClassificationResult) -> None:
        """Every classification decision is recorded here, append-only --
        this is what makes "classification is auditable" (Phase 3.1
        acceptance criterion) a real, queryable guarantee rather than
        something only true if a caller remembers to log it."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO classifications (
                    target, classification, risk_level, capabilities_detected,
                    matched_rules, reason, evidence, repository_commit,
                    policy_version, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.target,
                    result.classification.value,
                    result.risk_level.value,
                    json.dumps([c.value for c in result.capabilities_detected]),
                    json.dumps(list(result.matched_rules)),
                    result.reason,
                    json.dumps(list(result.evidence)),
                    result.repository_commit,
                    result.policy_version,
                    _now(),
                ),
            )
            conn.commit()

    def get_classification_history(self, target: str, repository_commit: str) -> list[ClassificationResult]:
        """Every classification ever recorded for this target at this
        commit, oldest first -- e.g. if re-run under a newer policy_version,
        both decisions remain visible, not just the latest."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM classifications
                WHERE target = ? AND repository_commit = ?
                ORDER BY row_id ASC
                """,
                (target, repository_commit),
            ).fetchall()
        return [_row_to_classification_result(row) for row in rows]

    def get_latest_classification(self, target: str, repository_commit: str) -> ClassificationResult | None:
        history = self.get_classification_history(target, repository_commit)
        return history[-1] if history else None

    def get_all_classifications(self, repository_commit: str) -> list[ClassificationResult]:
        """Current view: the latest classification per distinct target at
        this commit -- mirrors get_all_nodes/get_all_edges/get_all_evidence.
        Backs Phase 3.9's runtime audit (safety class counts across every
        classified target, not just one)."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT c.* FROM classifications c
                INNER JOIN (
                    SELECT target, MAX(row_id) AS max_row_id
                    FROM classifications WHERE repository_commit = ?
                    GROUP BY target
                ) latest ON c.target = latest.target AND c.row_id = latest.max_row_id
                WHERE c.repository_commit = ?
                """,
                (repository_commit, repository_commit),
            ).fetchall()
        return [_row_to_classification_result(row) for row in rows]

    # -- Execution environments (Phase 3.2) ----------------------------------

    def insert_execution_environment(self, environment: ExecutionEnvironment) -> None:
        """Makes "container configuration is auditable" (Phase 3.2) real --
        this is also what future RUNTIME Evidence's environment_id (Phase
        1.3) will point at."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO execution_environments (
                    environment_id, backend, image, network_enabled,
                    memory_limit_mb, cpu_limit, timeout_seconds,
                    non_privileged, read_only_filesystem, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    environment.environment_id,
                    environment.backend,
                    environment.image,
                    int(environment.network_enabled),
                    environment.memory_limit_mb,
                    environment.cpu_limit,
                    environment.timeout_seconds,
                    int(environment.non_privileged),
                    int(environment.read_only_filesystem),
                    _now(),
                ),
            )
            conn.commit()

    def get_execution_environment_history(self, environment_id: str) -> list[ExecutionEnvironment]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM execution_environments WHERE environment_id = ? ORDER BY row_id ASC",
                (environment_id,),
            ).fetchall()
        return [_row_to_execution_environment(row) for row in rows]

    def get_latest_execution_environment(self, environment_id: str) -> ExecutionEnvironment | None:
        history = self.get_execution_environment_history(environment_id)
        return history[-1] if history else None

    # -- Scenarios (Phase 3.4) -----------------------------------------------

    def insert_scenario(self, scenario: Scenario) -> None:
        """Append-only, like everything else -- re-generating scenarios for
        the same target at the same commit (e.g. under a changed policy) is
        a conflicting write for the same natural key (scenario_id), kept
        side by side as history, same as Node/Edge (Phase 1.2's "conflicts
        are representable")."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO scenarios (
                    scenario_id, target_entity_id, description, required_inputs,
                    dependencies, expected_observable_points, safety_class,
                    executable, unexecutable_reason, detail, repository_version,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario.scenario_id,
                    scenario.target_entity_id,
                    scenario.description,
                    json.dumps(list(scenario.required_inputs)),
                    json.dumps(list(scenario.dependencies)),
                    json.dumps(list(scenario.expected_observable_points)),
                    scenario.safety_class.value,
                    int(scenario.executable),
                    scenario.unexecutable_reason.value if scenario.unexecutable_reason else None,
                    scenario.detail,
                    scenario.repository_version,
                    _now(),
                ),
            )
            conn.commit()

    def get_scenario_history(self, scenario_id: str, repository_version: str) -> list[Scenario]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM scenarios
                WHERE scenario_id = ? AND repository_version = ?
                ORDER BY row_id ASC
                """,
                (scenario_id, repository_version),
            ).fetchall()
        return [_row_to_scenario(row) for row in rows]

    def get_latest_scenario(self, scenario_id: str, repository_version: str) -> Scenario | None:
        history = self.get_scenario_history(scenario_id, repository_version)
        return history[-1] if history else None

    def get_scenarios(self, repository_version: str) -> list[Scenario]:
        """Current view: the latest row per distinct scenario_id at this commit."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT s.* FROM scenarios s
                INNER JOIN (
                    SELECT scenario_id, MAX(row_id) AS max_row_id
                    FROM scenarios WHERE repository_version = ?
                    GROUP BY scenario_id
                ) latest ON s.scenario_id = latest.scenario_id AND s.row_id = latest.max_row_id
                WHERE s.repository_version = ?
                ORDER BY s.row_id ASC
                """,
                (repository_version, repository_version),
            ).fetchall()
        return [_row_to_scenario(row) for row in rows]
