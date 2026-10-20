"""Exercise default parsing, neural retrieval and lifecycle without composing providers."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from galmuri import Principal
from galmuri.configuration.project import load_project
from galmuri.retrieval import FastEmbedEmbedding, SQLiteVectorStore
from galmuri.scaffolding.project import create_project

from .observations import checkpoints, vectors
from .permissions import exercise

QUERY = "몸이 좋지 않을 때 누구를 찾아가야 하나요?"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(project, evidence):
    """Use the generated App as-is; environment only selects model cache location."""
    project, evidence = Path(project).resolve(), Path(evidence).resolve()
    create_project(project)
    loaded = load_project(project)
    runtime = loaded.runtime()
    app = runtime.apps["sample"]
    anonymous = Principal()
    store_path = loaded.database.parent / "vectors.sqlite3"
    checks = []
    report = {
        "started": datetime.now(UTC).isoformat(),
        "project": str(project),
        "embedding": asdict(app.retrieval.embedding.spec),
        "store": type(app.retrieval.store).__qualname__,
        "checks": checks,
    }
    evidence.mkdir(parents=True, exist_ok=True)

    def save():
        (evidence / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record(name, **data):
        checks.append({"name": name, "passed": True, **data})
        save()

    def query(mode="vector", principal=anonymous):
        return runtime.search("sample", QUERY, principal, mode=mode)

    def settle():
        require(runtime.drain(max_jobs=100) < 100, "Acceptance exceeded work budget")
        status = runtime.status("sample")
        require(
            all(job["state"] == "SUCCEEDED" for job in status["jobs"]),
            f"Ingestion did not settle: {status['jobs']}",
        )
        require(
            all(job["state"] in {"PUBLISHED", "SUPERSEDED"} for job in status["indexing"]["jobs"]),
            "Indexing did not settle",
        )
        require(
            all(job["state"] == "SUCCEEDED" for job in status["indexing"]["cleanup"]),
            "Vector cleanup did not settle",
        )
        snapshots = checkpoints(loaded.database)
        require(
            all(not item["retains_content"] and not item["retains_parsed"] for item in snapshots),
            "Published ingestion retained private retry payloads",
        )
        return status

    try:
        require(isinstance(app.retrieval.embedding, FastEmbedEmbedding), "Wrong default embedding")
        require(isinstance(app.retrieval.store, SQLiteVectorStore), "Wrong default vector store")
        require(app.retrieval.embedding.spec.dimensions == 384, "Expected real 384d model")
        require(app.handler.durable_ingestion, "Default App did not resolve built-in ingestion")
        require(not (project / "apps/sample/ingestion").exists(), "Generated custom handler")
        require(loaded.identity is not None, "Generated project has no account directory")
        require(loaded.caller().subject == "anonymous", "Generated caller inferred an owner")
        description = runtime.describe("sample", anonymous)
        config = description["configuration"]
        require(config["source"]["discovery"] == "snapshot_scan", "Discovery not described")
        require("read" in config["source"]["capabilities"], "Missing source read capability")
        require(
            config["ingestion"]["stages"] == ["read", "parse", "prepare", "publish"],
            "Missing default stage descriptions",
        )
        require(
            config["ingestion"]["permissions"] == {"read": ["*"], "write": ["*"]},
            "Generated settings did not resolve public read/write defaults",
        )
        require(
            set(config["defaults_applied"]) >= {"parser", "ingestion", "readers", "retrieval"},
            "Default origins were lost during project/runtime resolution",
        )
        require(
            description["operations"]["search"]["properties"]["mode"]["enum"]
            == ["lexical", "vector", "hybrid"],
            "Search input schema is incomplete",
        )
        require("write" not in description["operations"], "Readonly source advertised writes")
        record("unchanged_source_only_scaffold_and_resolved_metadata", descriptor=description)

        runtime.sync()
        status = settle()
        lexical, vector, hybrid = query("lexical"), query(), query("hybrid")
        require(lexical == [], "Natural paraphrase unexpectedly matched literal text")
        require(vector and vector[0]["metadata"]["name"] == "clinic.md", "Semantic ranking missed")
        require(hybrid and hybrid[0]["key"] == vector[0]["key"], "Hybrid ranking missed")
        clinic = vector[0]
        require(app.retrieval.embedding._model is not None, "Actual ONNX model was not loaded")
        actual_vectors = vectors(store_path)
        require(len(actual_vectors) == 2, "Expected two generated sample vectors")
        require(
            all(item["dimensions"] == 384 for item in actual_vectors), "Wrong stored dimensions"
        )
        require(
            all(
                clinic["text"][item["start"] : item["end"]] == item["text"]
                for item in clinic["chunks"]
            ),
            "Unicode anchors do not match",
        )
        record(
            "real_multilingual_model_sqlite_and_hybrid",
            lexical=lexical,
            vector=vector,
            hybrid=hybrid,
            vectors=actual_vectors,
        )
        record(
            "read_parse_publish_and_payload_release",
            status=status,
            checkpoints=checkpoints(loaded.database),
        )

        require(
            runtime.read("sample", clinic["key"], anonymous)["text"] == clinic["text"],
            "Source-only default policy did not permit public document reads",
        )
        record("source_only_default_public_read_without_fabricated_owner")
        exercise(runtime, loaded.identity.db.path, store_path, clinic, query, require, record)

        runtime = load_project(project).runtime()
        require(query()[0]["build"] == clinic["build"], "Restart lost current generation")
        record("fresh_runtime_restart", build=clinic["build"])

        fixture = project / "apps/sample/fixtures/clinic.md"
        fixture.write_text(
            "# 진료 안내\n\n아픈 사람은 병원의 의사에게 진료를 받습니다.\n"
            "예약 확인 번호는 DEFAULT-UPDATED-73입니다.\n",
            encoding="utf-8",
        )
        runtime.collect("sample", force=True)
        require(
            clinic["key"] not in {item["key"] for item in query()},
            "Accepted update intent exposed old semantic generation",
        )
        record("update_intent_withdrawal_before_processing")
        settle()
        updated = query()[0]
        require(
            updated["key"] == clinic["key"] and "DEFAULT-UPDATED-73" in updated["text"],
            "Updated body was not published",
        )
        initial_ids = {item["id"] for item in clinic["chunks"]}
        require(
            initial_ids.isdisjoint({item["id"] for item in vectors(store_path)}),
            "Old vectors survived update cleanup",
        )
        record(
            "updated_document_and_physical_vector_cleanup",
            result=updated,
            vectors=vectors(store_path),
        )

        deleted_ids = {item["id"] for item in updated["chunks"]}
        fixture.unlink()
        runtime.collect("sample", force=True)
        require(
            clinic["key"] not in {item["key"] for item in query()},
            "Accepted delete intent exposed old semantic generation",
        )
        settle()
        require(clinic["key"] not in {item["key"] for item in query()}, "Deleted document returned")
        remaining = vectors(store_path)
        require(
            deleted_ids.isdisjoint({item["id"] for item in remaining}),
            "Deleted vectors survived physical cleanup",
        )
        require(len(remaining) == 1, "Unexpected remaining vector count")
        record("delete_intent_and_physical_cleanup", vectors=remaining, status=runtime.status())
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["completed"] = datetime.now(UTC).isoformat()
        save()
    return report
