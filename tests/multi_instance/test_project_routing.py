"""Settings aliases and schema namespaces select coherent persistence bundles."""

from pathlib import Path

from galmuri import Principal
from galmuri.configuration.project import load_project
from galmuri.exposure.service import Service
from galmuri.retrieval import PostgresVectorStore
from tools.multi_instance_acceptance.fixture import publish


def test_project_alias_namespace_vectors_identity_and_explorer_isolation(scenario, tmp_path):
    config, _ = scenario
    primary, archive, tenant = config["schema"], config["schema"] + "_a", config["schema"] + "_t"
    config["extra_schemas"] = [archive, tenant]
    publish(config["source"], {"doc0": {"version": "1", "text": "shared original document"}})
    project_path = tmp_path / "application"
    settings = project_path / "config" / "settings.py"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "from galmuri import App, DatabaseConfig\n"
        "from galmuri.retrieval import PostgresVectorStore, RetrievalConfig\n"
        "from tools.multi_instance_acceptance.fixture import Source, Embedding, ingest\n"
        "DSN = os.environ['FRAMEWORK_POSTGRES_DSN']\n"
        f"DATABASES = {{'default': {{'ENGINE':'postgresql','DSN':DSN,'SCHEMA':{primary!r}}},"
        f"'archive': {{'ENGINE':'postgresql','DSN':DSN,'SCHEMA':{archive!r}}}}}\n"
        "IDENTITY_DATABASE = 'default'\n"
        f"source = Source({config['source']!r})\n"
        "def retrieval(schema):\n"
        "    return RetrievalConfig(Embedding(), PostgresVectorStore(DSN, schema=schema))\n"
        "APPS = [\n"
        f"    App('primary', source, ingest, retrieval=retrieval({primary!r})),\n"
        f"    App('archive', source, ingest, retrieval=retrieval({archive!r}), "
        "database=DatabaseConfig(alias='archive')),\n"
        "    App('tenant', source, ingest, retrieval=RetrievalConfig(embedding=Embedding()), "
        f"database=DatabaseConfig(alias='archive', namespace={tenant!r})),\n"
        "    App('automatic', source),\n"
        "]\n",
        encoding="utf-8",
    )
    project = load_project(project_path)
    instance = project.runtime()
    assert isinstance(instance.apps["automatic"].retrieval.store, PostgresVectorStore)
    assert instance.apps["automatic"].retrieval.store._database.schema == primary
    assert isinstance(instance.apps["tenant"].retrieval.store, PostgresVectorStore)
    assert instance.apps["tenant"].retrieval.store._database.schema == tenant
    assert instance.apps["tenant"].retrieval.mode == "hybrid"
    assert {name: instance.database[name].schema for name in ("primary", "archive", "tenant")} == {
        "primary": primary,
        "archive": archive,
        "tenant": tenant,
    }
    assert project.identity.db.schema == primary
    for name in ("primary", "archive", "tenant"):
        instance.sync(name)
        assert instance.search(name, "semantic query", Principal())[0]["key"] == "doc0"
    instance.documents.set_permissions("primary", "doc0", (), ())
    assert instance.search("primary", "semantic query", Principal()) == []
    service = Service(instance, identity=project.identity)
    for name in ("archive", "tenant"):
        assert instance.search(name, "semantic query", Principal())[0]["version"] == "1"
        documents = service.call("documents", {"app": name}, Principal())
        assert documents["ok"], documents
        assert documents["result"]["total"] == 1
    assert service.call("documents", {"app": "primary"}, Principal())["result"]["total"] == 0
    # Reloading a project shares identity rows rather than creating another directory.
    account = project.identity.create_user("shared-admin", "correct horse battery staple")
    reloaded = load_project(project_path)
    assert reloaded.identity.list_users()[0]["id"] == account["id"]
    assert Path(project.database).suffix == ".sqlite"
