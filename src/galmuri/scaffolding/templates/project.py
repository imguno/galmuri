"""The project contains configuration; users create and register their own apps."""

README = """# Your Galmuri project

Create an app from this directory:

```sh
python manage.py startapp sample
```

Register it in config/settings.py:

```python
APPS = ["apps.sample.app:sample"]
```

Add more entries to APPS when creating additional apps. Each App binds one source
connection to its processing, retrieval and execution policy.

Edit apps/sample/source/local.py to connect your source, and apps/sample/app.py
to select your processing and retrieval configuration. The fixtures and skills
directories contain editable sample content and usage instructions.

Use `python manage.py startapp other --process` to include runnable functions in
views/ and their process.py binding. Register that app explicitly as well.
EXPOSURE_ADAPTERS in config/settings.py registers custom exposure factories;
EXPOSURES configures their options.

Run your registered apps:

```sh
python manage.py sync
python manage.py call search --app sample --mode lexical --query welcome
python manage.py serve mcp
```

App defaults include local multilingual embeddings and vector storage. The first
embedding operation downloads model weights. Set retrieval=None on an App for
lexical-only processing without model downloads.
"""
