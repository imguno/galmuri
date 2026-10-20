FROM python:3.13-slim
# Build with: docker build --build-context duru=../duru -t galmuri-local .
COPY --from=duru pyproject.toml /opt/access/pyproject.toml
COPY --from=duru README.md /opt/access/README.md
COPY --from=duru README.ko.md /opt/access/README.ko.md
COPY --from=duru LICENSE /opt/access/LICENSE
COPY --from=duru MANIFEST.in /opt/access/MANIFEST.in
COPY --from=duru src /opt/access/src
RUN python -m pip install --no-cache-dir /opt/access
WORKDIR /opt/galmuri
COPY pyproject.toml MANIFEST.in LICENSE *.md ./
COPY src ./src
COPY skills ./skills
ARG FRAMEWORK_EXTRAS=mcp,grpc
RUN python -m pip install --no-cache-dir ".[${FRAMEWORK_EXTRAS}]"
WORKDIR /workspace
ENTRYPOINT ["python", "-m", "galmuri"]
CMD ["--help"]
