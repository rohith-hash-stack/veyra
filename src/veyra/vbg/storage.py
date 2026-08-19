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
from .models import Edge, Node, RelationshipType, RepositoryRecord, VerificationState
from .questions import Answer, AnswerStatus, Question, QuestionCategory
from .safety import Capability, ClassificationResult, RiskLevel, SafetyClass

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
