"""Generated project, real model and remote storage: executable lifecycle evidence."""

import importlib
import importlib.util
import json
import sys
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from galmuri import Principal
from galmuri.retrieval import FastEmbedEmbedding, QdrantVectorStore
from galmuri.runtime import Runtime
from galmuri.scaffolding.project import create_project

from .remote import observe

QUERY = "몸이 좋지 않을 때 누구를 찾아가야 하나요?"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def generated_app(project):
    # A private package name avoids collisions with applications loaded by other tests.
    name = "acceptance_" + uuid.uuid4().hex
    path = project / "apps" / "sample"
    spec = importlib.util.spec_from_file_location(
        name, path / "__init__.py", submodule_search_locations=[str(path)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return importlib.import_module(name + ".app").sample


def run(project, evidence, *, url, cache=None, model=None, api_key=None):
    """Creates an isolated project; never deletes collections or existing directories."""
    project, evidence = Path(project).resolve(), Path(evidence).resolve()
    create_project(project, retrieval=True)
    app = generated_app(project)
    prefix = "acceptance_" + uuid.uuid4().hex
    config = replace(
        app.retrieval,
        embedding=FastEmbedEmbedding(
            model=model or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            cache_dir=cache,
        ),
        store=QdrantVectorStore(url, prefix=prefix, api_key=api_key),
    )
    app = replace(app, retrieval=config)
    state = project / ".runtime" / "state.sqlite"
    runtime = Runtime(state, [app])
    public, developer = Principal(), Principal("developer", frozenset({"dev"}))
    checks = []
    report = {
        "started": datetime.now(UTC).isoformat(),
        "project": str(project),
        "embedding": asdict(config.embedding.spec),
        "fingerprint": config.fingerprint,
        "store_prefix": prefix,
        "checks": checks,
    }
    evidence.mkdir(parents=True, exist_ok=True)

    def record(name, **data):
        checks.append({"name": name, "passed": True, **data})
        (evidence / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def query(principal=public, mode="vector"):
        return runtime.search("sample", QUERY, principal, mode=mode)

    def remote(fingerprint=None):
        return observe(url, prefix, fingerprint or config.fingerprint, api_key)

    def drain():
        processed = runtime.drain(max_jobs=100)
        status = runtime.indexing.status("sample")
        require(processed < 100, "Index worker exceeded acceptance work budget")
        require(
            all(job["state"] in {"PUBLISHED", "SUPERSEDED"} for job in status["jobs"]),
            f"Index jobs did not settle: {status}",
        )
        require(
            all(job["state"] == "SUCCEEDED" for job in status["cleanup"]),
            f"Cleanup did not settle: {status}",
        )
        return status

    try:
        runtime.sync()
        lexical, vector, hybrid = query(mode="lexical"), query(), query(mode="hybrid")
        require(lexical == [], "Natural paraphrase unexpectedly had a lexical match")
        require(vector and vector[0]["key"] == "clinic.md", "Neural ranking missed clinic")
        require(hybrid and hybrid[0]["key"] == "clinic.md", "Hybrid ranking missed clinic")
        clinic = vector[0]
        for chunk in clinic["chunks"]:
            require(
                clinic["text"][chunk["start"] : chunk["end"]] == chunk["text"],
                "Chunk anchors do not match original Unicode text",
            )
        initial = remote()
        require(len(initial["ids"]) == 3, "Expected three actual remote sample points")
        require(all(not payload for payload in initial["payloads"]), "Remote payload leaked data")
        record("neural_paraphrase_and_hybrid", lexical=lexical, vector=vector, hybrid=hybrid)
        record("remote_vectors_and_unicode_anchors", remote=initial)

        require("development.dev.md" not in {item["key"] for item in vector}, "ACL leak")
        require(
            "development.dev.md" in {item["key"] for item in query(developer)},
            "Developer cannot retrieve restricted sample",
        )
        runtime.documents.set_permissions("sample", "clinic.md", ("group:dev",), ())
        require("clinic.md" not in {item["key"] for item in query()}, "Revoked grant leaked")
        require("clinic.md" in {item["key"] for item in query(developer)}, "Grant lost")
        require(remote()["ids"] == initial["ids"], "ACL-only change rebuilt remote embeddings")
        runtime.documents.set_permissions("sample", "clinic.md", ("*",), ("group:dev",))
        record("live_acl_revocation_without_reembedding")

        # A fresh provider instance has no in-memory collection dimension cache.
        fresh_store = QdrantVectorStore(url, prefix=prefix, api_key=api_key)
        app = replace(app, retrieval=replace(config, store=fresh_store))
        runtime = Runtime(state, [app])
        require(query()[0]["build"] == clinic["build"], "Restart lost current vector generation")
        record("fresh_provider_restart", build=clinic["build"])

        fixture = project / "apps" / "sample" / "fixtures" / "clinic.md"
        fixture.write_text(
            "# 진료 안내\n\n아픈 사람은 병원의 의사에게 진료를 받습니다.\n"
            "예약 확인 번호는 UPDATED-73입니다.\n",
            encoding="utf-8",
        )
        runtime.collect("sample", force=True)
        require("clinic.md" not in {item["key"] for item in query()}, "Old update intent leaked")
        record("update_intent_withdraws_stale_vectors_before_processing")
        drain()
        updated = query()[0]
        require(updated["key"] == "clinic.md", "Updated clinic was not republished")
        require("UPDATED-73" in updated["text"], "Updated vector returned old document")
        old_ids = {chunk["id"] for chunk in clinic["chunks"]}
        require(old_ids.isdisjoint(remote()["ids"]), "Old update vectors were not deleted")
        record("update_rebuild_and_physical_cleanup", updated=updated, remote=remote())

        old_build = updated["build"]
        scheduled = runtime.indexing.reindex("sample")
        require(scheduled["scheduled"] == 3, "Explicit reindex did not schedule all documents")
        require(query() == [], "Reindex exposed withdrawn old generations")
        drain()
        require(query()[0]["build"] != old_build, "Reindex reused an old build")
        require(len(remote()["ids"]) == 3, "Reindex leaked old physical points")
        record("explicit_reindex_new_generation", scheduled=scheduled, remote=remote())

        old_fingerprint = config.fingerprint
        config = replace(app.retrieval, revision="acceptance-generation-2")
        app = replace(app, retrieval=config)
        try:
            Runtime(state, [app])
        except ValueError:
            pass
        else:
            raise RuntimeError("Changed config was activated without an explicit command")
        runtime = Runtime(state, [app], activate=True)
        require(query() == [], "Configuration activation mixed older vector generations")
        drain()
        require(query()[0]["fingerprint"] == config.fingerprint, "Wrong active fingerprint")
        require(remote(old_fingerprint)["ids"] == [], "Retired config retained remote points")
        record("explicit_configuration_activation", fingerprint=config.fingerprint, remote=remote())

        deleted_ids = {chunk["id"] for chunk in query()[0]["chunks"]}
        fixture.unlink()
        runtime.collect("sample", force=True)
        require("clinic.md" not in {item["key"] for item in query()}, "Deleted intent leaked")
        record("delete_intent_withdraws_vectors_before_processing")
        drain()
        require("clinic.md" not in {item["key"] for item in query()}, "Deleted document returned")
        require(deleted_ids.isdisjoint(remote()["ids"]), "Deleted remote points survived cleanup")
        require(len(remote()["ids"]) == 2, "Unexpected final remote vector count")
        record("deletion_and_physical_cleanup", remote=remote(), status=runtime.indexing.status())
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["completed"] = datetime.now(UTC).isoformat()
        (evidence / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report
