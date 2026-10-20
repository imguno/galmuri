# 첫 문서 서비스 개발하기

[English](build-an-integration.md) · 한국어 · [개요](../README.ko.md)

기사 파일을 읽어 검색 가능한 문서로 만들고, 다른 애플리케이션에 제공하는
서비스를 개발합니다. 프로젝트와 첫 앱을 생성한 다음, 사용자 프로젝트에
JSON 파서와 출력 어댑터를 작성합니다. Galmuri는 연결한 구현을 실행하고
문서 갱신·접근권한 검사·복구를 관리합니다.

**App**은 하나의 소스 연결과 그 소스의 처리·검색·실행 정책을 묶는 단위입니다.
한 프로젝트에 여러 App을 등록할 수 있고, 익스포터는 공통 서비스를 통해
이 App들을 제공합니다. RAG 애플리케이션은 기존 LLM·답변 로직을 유지하면서
문서와 검색 결과를 이용할 수 있습니다.

이 예제는 **Galmuri 0.2.0** 기준입니다. 첫 예제는 벡터 색인을 끄므로
모델 다운로드·모델 API 키·외부 서비스가 필요하지 않습니다.
검색 옵션과 기존 상태 업그레이드는 [검색 가이드](search.ko.md)를 참고하세요.
Python 3.12 이상을 사용하세요. 아래 셸 명령은 Linux/macOS 기준입니다.
Duru는 의존성으로 설치되므로 별도 저장소 체크아웃이 필요하지 않습니다.

## 1. 사용자 프로젝트 생성

Galmuri를 설치한 다음 프로젝트와 첫 앱을 생성합니다.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'galmuri[mcp]==0.2.0'
python -m galmuri startproject catalog
cd catalog
python manage.py startapp sample
mkdir -p apps/sample/views
touch apps/sample/views/__init__.py
```

생성된 `config/settings.py`에서 앱을 등록하세요.

```python
APPS = ["apps.sample.app:sample"]
```

이후에는 사용자 프로젝트의 파일을 수정합니다. **첫 sync 전에** 아래 변경을 적용하세요.

생성된 `apps/sample/source/local.py`는 Duru의 읽기 전용 로컬 공급자를
`apps/sample/fixtures/`에 연결합니다. 예제에서는 이 커넥터를 사용합니다.
Duru가 파일 IO를 담당하고, 파서는 읽기가 끝난 `File`을 받습니다.
자체 API 커넥터는 [Duru 공급자 계약](https://github.com/imguno/duru#extend-the-contract)을
구현한 뒤 같은 `App.source`에 연결할 수 있습니다.

## 2. 문서와 파서 작성

`apps/sample/fixtures/article.json`을 만듭니다.

```json
{
  "title": "Observatory handbook",
  "body": "A quasar is the bright active nucleus of a distant galaxy."
}
```

`apps/sample/views/articles.py`를 만듭니다.

```python
import json

from galmuri import Document, File
from galmuri.parsing import parse_auto


def parse_article(file: File) -> tuple[Document, ...]:
    name = str(file.ref.metadata.get("name", ""))
    if not name.lower().endswith(".json"):
        return parse_auto(file)

    record = json.loads(file.text)
    if not isinstance(record, dict):
        raise ValueError("An article must be a JSON object")
    title, body = record["title"], record["body"]
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("Article title and body must be strings")

    return (
        Document(
            key=file.ref.key,
            text=f"{title}\n\n{body}",
            metadata={**file.ref.metadata, "title": title, "format": "article"},
        ),
    )
```

입력 `File`에는 바이트 `content`, UTF-8로 해석한 `text`, 소스 키·버전·메타데이터를
가진 `ref`가 있습니다. 출력은 `Document` 튜플입니다. 각 문서는 안정적인 `key`,
검색할 `text`, JSON으로 직렬화 가능한 `metadata`를 가집니다. 이 파서는 파일당
문서 하나를 만들고 소스 키를 문서 키로 사용합니다. 기존 Markdown 샘플은
`parse_auto`로 처리됩니다.

`json.loads` 대신 별도 HTML·PDF 파싱 라이브러리를 호출해도 됩니다.
그 결과를 동일한 `Document` 계약으로 변환하세요. 함수 등록 시점에 실행되는 것이
아니라, 처리 작업이 실행될 때 파서가 호출됩니다.

## 3. App에 연결

`apps/sample/app.py`를 다음으로 교체합니다.

```python
from galmuri import App, IngestConfig, ParsingConfig

from .source.local import source
from .views.articles import parse_article

sample = App(
    name="sample",
    source=source,
    parser=ParsingConfig(process=parse_article, revision="1"),
    ingestion=IngestConfig(readers=("*",), writers=()),
    retrieval=None,
)
```

호출 결과 `parse_article(...)`이 아닌 함수 참조 `parse_article`을 전달합니다.
기본 처리 경로가 파서를 실행하고 반환된 문서의 권한과 발행을 준비합니다.
여기서는 공개 읽기를 허용하고 쓰기는 거부합니다. 소스 자체도 읽기 전용입니다.

1절에서 `config/settings.py`에 직접 추가한 앱 등록을 유지하세요.

```python
APPS = ["apps.sample.app:sample"]
```

파일의 다른 설정은 유지하세요. 다른 소스용으로 `apps/manuals/app.py`와 App 객체를
만들었다면 그 import 경로를 `APPS`에 추가합니다. 소스마다 파서·스케줄·DB·벡터
저장소를 다르게 지정할 수 있습니다.

## 4. 발행 결과 확인

`catalog/`에서 실행합니다.

```sh
python manage.py sync
python manage.py call describe --app sample
python manage.py call search --app sample --mode lexical --query quasar
```

검색 응답의 `result`에 `Observatory handbook`으로 시작하는 문서가 있고,
`metadata.format`이 `article`인지 확인하세요. `key`는 소스에서 정한 불투명한
식별자입니다. 파일명으로 다시 만들지 말고 반환된 값을 사용합니다.

`KEY_FROM_SEARCH`를 실제 키로 바꿔 문서를 읽습니다.

```sh
python manage.py call read --app sample --params '{"document_key":"KEY_FROM_SEARCH"}'
```

JSON 본문을 고치고 `sync`하면 새 소스 버전을 처리합니다. 파서 동작을 바꾸었다면
`ParsingConfig.revision`을 올리고 다음을 실행합니다.

```sh
python manage.py activate
python manage.py sync
```

활성화는 변경된 처리 계약을 승인하고 이전 작업의 발행을 차단합니다.
함수 소스를 자동으로 해시하지 않습니다. 로컬 파일 삭제도 이후 sync에서 발견됩니다.

## RAG 클라이언트 연결

기존 애플리케이션에서 LLM과 답변 구성을 유지하세요.
동기화한 프로젝트의 MCP 서버는 `sample_describe`, `sample_search`,
`sample_read`를 제공합니다. 읽기 전용 소스이므로 `sample_write`는 등록하지 않습니다.

`mcpServers` 형식을 사용하는 클라이언트에서는 두 절대 경로를 바꿔 등록합니다.

```json
{
  "mcpServers": {
    "catalog": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": [
        "/absolute/path/to/catalog/manage.py",
        "serve",
        "mcp",
        "--workers",
        "0"
      ]
    }
  }
```

위 설정은 이미 동기화한 문서를 제공합니다. 워커를 별도로 실행하거나,
이 서버에서 변경 처리도 실행하려면 `--workers 0`을 생략하세요.
프로젝트 경로는 `manage.py`를 기준으로 결정됩니다.
설정을 저장하는 위치는 클라이언트마다 다릅니다.

현재 `catalog/` 안에서 `manage.py` 옆에 `mcp_client.py`를 만드세요.

```python
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    project = Path(__file__).resolve().parent
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(project / "manage.py"), "serve", "mcp", "--workers", "0"],
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(
                "sample_search", {"query": "quasar", "mode": "lexical"}
            )
            print(result.structuredContent)


if __name__ == "__main__":
    asyncio.run(main())
```

같은 환경에서 `python mcp_client.py`를 실행합니다. LLM 없이 공개 문서를 조회합니다.
이후 선택한 LLM에 반환된 본문과 소스 키를 전달해 답변을 구성할 수 있습니다.

제한된 문서는 계정 명령으로 계정에 연결된 토큰을 발급하고 서버 환경의
`FRAMEWORK_TOKEN_FILE`에 비공개 토큰 파일의 절대 경로를 지정합니다.
도구 인자의 계정명은 인증이 아닙니다. HTTP·gRPC·CLI도 같은 서비스를 사용합니다.
[계정과 외부 노출](reference.md#exposure-adapters)에서 추가 설정을 확인하세요.

## 5. 임베딩 활성화 (선택)

기존 `apps/sample/app.py`에 다음 import를 추가합니다.

```python
from galmuri import RetrievalConfig
```

기존 App 선언에서 `retrieval=None`만 `retrieval=RetrievalConfig(mode="hybrid")`로
바꾸세요. 소스·파서 revision·문서 권한은 현재 값을 유지합니다.

지정하지 않은 공급자는 로컬 다국어 FastEmbed와 App DB의 기본 벡터 저장소를
선택합니다. 첫 추론에서 모델을 다운로드합니다. `EMBEDDING_CACHE`로 기존 캐시를
지정할 수 있습니다.

```sh
python manage.py activate
python manage.py sync
python manage.py index-status --app sample
python manage.py call search --app sample --mode vector --query "What shines at a galaxy's center?"
```

관련 벡터 작업이 `PUBLISHED`인지 확인한 뒤 의미 검색을 평가하세요.
문서 발행과 벡터 발행은 별개입니다. sync가 끝나도 실패하거나 다음 재시도를 기다리는
벡터 작업이 있을 수 있습니다. `index --drain`은 현재 실행 가능한 작업을 처리하며,
상태는 `index-status`로 확인합니다.

모델과 저장소를 직접 고르려면 `apps/sample/retrieval.py`를 만듭니다.

```python
import os

from galmuri import RetrievalConfig
from galmuri.retrieval import FastEmbedEmbedding, QdrantVectorStore

retrieval = RetrievalConfig(
    embedding=FastEmbedEmbedding(
        model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir=os.environ.get("EMBEDDING_CACHE"),
    ),
    store=QdrantVectorStore(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY"),
    ),
    mode="hybrid",
)
```

이 설정은 접근 가능한 Qdrant 서비스와 `QDRANT_URL`이 필요합니다.
`app.py`에서 `from .retrieval import retrieval`을 추가하고 App의 인자를
`retrieval=retrieval`로 바꾼 뒤 활성화하세요. 파서나 LLM 답변 코드를 바꿀 필요는 없습니다.

기존 `Chunker`·`EmbeddingProvider`·`VectorStore` 구현체를 직접 전달하거나
`ChunkingConfig`·`EmbeddingConfig`로 함수를 연결할 수 있습니다.
[입출력 계약](reference.md#retrieval-input-and-output-contracts)과
[검색 함수·결합 전략 설정](search.ko.md)을 참고하세요.

## 처리·권한 기본값

파서만 바꾸면 기본 준비·발행 경로를 유지합니다.
`python manage.py startapp articles --process`는 `views/`의 여러 함수를
`Pipeline.default().then(Step(...))`로 연결한 예제를 만듭니다.
실행 전에 새 앱을 `APPS`에 등록하세요.

| 선언 | `retrieval` 생략 시 | 문서 권한 준비 |
| --- | --- | --- |
| 기본 처리, 선택적 `parser=...` | 로컬 임베딩·벡터 저장소 | `IngestConfig`와 설정 기본값 적용 |
| `process=Pipeline(...)` | 로컬 임베딩·벡터 저장소 | 문서로 끝나면 자동 준비, `IngestResult`로 끝나면 반환값의 권한 사용 |
| `process=my_function` 또는 이전 `handler=my_function` | 키워드 검색만 | 함수가 명시적인 권한을 가진 `IngestResult` 반환 |

전체 처리 함수에도 `retrieval=RetrievalConfig()`를 지정하면 벡터 색인이 활성화됩니다.
입력은 `File`, 출력은 `IngestResult`입니다. 로그나 직접 DB에 쓰는 것으로 완료를
알리지 않습니다. 전체 처리 함수는 파싱·권한 준비도 담당하므로 App의
`parser`·`ingestion` 옵션과 함께 지정하지 않습니다.

`DEFAULT_PERMISSIONS`는 기본 처리와 문서로 끝나는 파이프라인에서 생략된
`IngestConfig` 권한에 적용됩니다. 직접 반환한 최종 `IngestResult`의 권한을
덮어쓰지 않습니다. `Document`에서 권한을 생략하면 빈 권한입니다.
소스의 지원 기능과 검증된 계정 권한도 함께 적용됩니다.

## 6. 익스포터 구현 (선택)

기본 익스포터는 MCP·HTTP·gRPC·CLI 노출 어댑터입니다.
직접 구현하는 어댑터는 `Service`를 받고 `run()`을 구현합니다.
DB를 직접 열지 않고 서비스에서 권한 검사를 거친 결과를 받습니다.

빈 `exporters/__init__.py`와 `exporters/articles.py`를 만듭니다.

```python
import json

from galmuri import Principal


class ArticleExporter:
    def __init__(self, service, *, app="sample", query="quasar", limit=100):
        self.service = service
        self.app, self.query, self.limit = app, query, limit

    def run(self):
        response = self.service.call(
            "search",
            {"app": self.app, "query": self.query, "mode": "lexical", "limit": self.limit},
            Principal(),
        )
        if not response["ok"]:
            raise RuntimeError(response["error"]["code"])
        for document in response["result"]:
            print(json.dumps(document, ensure_ascii=False, allow_nan=False))
```

`config/settings.py`에서 클래스를 import하고 `EXPOSURE_ADAPTERS = {}`를 바꿉니다.

```python
from ..exporters.articles import ArticleExporter

EXPOSURE_ADAPTERS = {"articles": ArticleExporter}
EXPOSURES["articles"] = {"app": "sample", "query": "quasar", "limit": 100}
```

기존 HTTP·gRPC·MCP 설정은 유지합니다. sync 후 실행합니다.

```sh
python manage.py serve articles --workers 0
```

조건에 맞는 공개 문서를 최대 100개까지 JSON Lines로 출력하고 종료합니다.
이 예제는 익명 `Principal()`을 사용하므로 제한된 문서를 읽을 수 없습니다.
네트워크 익스포터는 인증기를 통해 검증된 자격 증명을 받아 서비스에 전달해야 합니다.
요청 인자에서 사용자 신원을 만들면 안 됩니다.

이 예제는 검색 결과 내보내기이며 전체 백업이나 원자적인 전체 문서 스냅샷은 아닙니다.
다른 시스템으로 전송하는 익스포터는 전송·중복 실행·재시도를 직접 책임집니다.
노출 어댑터 인터페이스가 영속 전송 큐를 제공하지는 않습니다.

## 7. 직접 구현한 커넥터 추가

두 번째 앱을 생성합니다.

```sh
python manage.py startapp manuals
```

기본으로 생성된 로컬 폴더 연결을 대신해, Duru의 `Provider` 인터페이스로
불변 문서 하나를 제공하는 소스를 구현합니다.
`apps/manuals/source/manual.py`를 만드세요.

```python
import hashlib
import io

from duru import Conflict, NotFound, Provider, ResourceInfo


class GuideProvider(Provider):
    identity = "example-guide:v1"
    root_uri = "guide://manual"
    content = b"The quasar operations guide is supplied by a custom connector."

    def stat(self, uri):
        if uri != self.root_uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        return ResourceInfo(
            uri,
            "manual.txt",
            revision=hashlib.sha256(snapshot).hexdigest(),
            size=len(snapshot),
        )

    def open(self, uri, *, expected_revision=None):
        if uri != self.root_uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        revision = hashlib.sha256(snapshot).hexdigest()
        if expected_revision is not None and expected_revision != revision:
            raise Conflict("Guide revision changed")
        return io.BufferedReader(io.BytesIO(snapshot))
```

`apps/manuals/app.py`를 다음 내용으로 바꿉니다.

```python
from galmuri import App

from .source.manual import GuideProvider

manuals = App(name="manuals", source=GuideProvider(), retrieval=None)
```

`config/settings.py`에 추가합니다.

```python
APPS.append("apps.manuals.app:manuals")
```

한 프로젝트에서 두 App을 실행합니다.

```sh
python manage.py sync
python manage.py call search --app sample --query quasar
python manage.py call search --app manuals --query quasar
```

`sample`은 로컬 파일과 커스텀 파서를, `manuals`는 직접 만든 커넥터와 기본 파서를
사용합니다. 같은 익스포터가 두 App을 제공할 수 있습니다.
검색은 App을 명시적으로 선택합니다. 여러 App 결과를 합치려면 소비자나 커스텀
익스포터에서 조합합니다. 멀티소스는 한 프로젝트에서 여러 소스 App을 독립적으로
설정·운영한다는 의미이며 자동으로 통합 순위를 계산하는 의미는 아닙니다.
앞서 만든 `articles` 익스포터로 `manuals`를 출력하려면 실행 전에 설정에서
`EXPOSURES["articles"]["app"] = "manuals"`로 바꾸세요.

실제 API 커넥터에서는 바이트 예제 대신 해당 클라이언트 라이브러리를 연결합니다.
`stat`은 식별자·표시 이름·버전을 반환하고, `open`은 요청 버전에 맞는 바이트
스냅샷을 반환하거나 `Conflict`를 발생시켜야 합니다. 버전만 확인한 뒤 검증되지
않은 가변 내용을 반환하면 안 됩니다. 반환된 스트림은 호출자가 닫습니다.
컬렉션에는 `Listable`을 추가하고, 원본이 보장하는 변경 기능만 선언하세요.
인증 정보는 배포 설정에서 생성자 인자로 주입합니다. 서비스 IO는 커넥터,
문서 변환은 파서에 둡니다.
