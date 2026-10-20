# 갈무리 (Galmuri)

[English](README.md) · 한국어

**여러 저장소의 문서를 수집·가공·제공하는 서비스를 만드는 Python 프레임워크입니다.**

로컬 파일, Google Drive 문서, Slack 메시지나 직접 만든 데이터 소스를 연결하세요.
가져온 내용을 어떻게 변환하고 색인할지 정하고, MCP·HTTP·gRPC·CLI 또는 직접 구현한
인터페이스로 다른 애플리케이션에 제공할 수 있습니다.

개발은 생성된 사용자 프로젝트에서 진행합니다. 소스 연결 코드, 문서 처리 함수,
외부 제공 어댑터를 필요한 부분만 구현하거나 교체하세요. Galmuri는 앱에 지정한
정책에 따라 실행하며 체크포인트, 문서 갱신, 접근권한 검사, 재시도를 관리합니다.

## 첫 프로젝트 만들기

**Python 3.12 이상**이 필요합니다. PyPI에서 Galmuri를 설치하세요.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'galmuri[mcp,grpc]==0.2.0'
```

프로젝트를 만든 다음, 그 안에 첫 앱을 생성합니다.

```sh
python -m galmuri startproject example
cd example
python manage.py startapp sample
```

`startproject`는 프로젝트 설정과 `manage.py`를 만듭니다. `startapp`은 소스 연결과
샘플 문서가 있는 앱을 만듭니다. `config/settings.py`를 열어 생성한 앱을 등록하세요.

```python
APPS = ["apps.sample.app:sample"]
```

생성된 앱은 로컬 폴더, 기본 파서, 로컬 다국어 임베딩, SQLite를 사용합니다.
첫 동기화 때 모델 가중치를 다운로드하며 LLM API 키는 필요하지 않습니다.
기존 모델 캐시가 있다면 동기화 전에 `EMBEDDING_CACHE`로 지정할 수 있습니다.

```sh
python manage.py sync --app sample
python manage.py index-status --app sample
python manage.py call search --app sample --mode lexical --query welcome
python manage.py serve http
```

검색 명령은 생성된 `welcome.md` 문서를 반환합니다.
<http://127.0.0.1:8000/dashboard>에서 문서를 확인하고, Ctrl+C로 서버를 종료하세요.
문서 처리와 벡터 색인은 별도로 완료되므로 의미 검색을 사용하기 전에
index status에서 대기·실패한 작업을 확인하세요.

모델 다운로드 없이 시작하는 예제는
[첫 문서 서비스 개발하기](guides/build-an-integration.ko.md)를 참고하세요.

## 앱 개발하기

두 생성 명령으로 만들어지는 주요 파일은 다음과 같습니다.

```text
example/
├── manage.py
├── config/
│   └── settings.py
└── apps/
    └── sample/
        ├── app.py
        ├── source/
        │   └── local.py
        ├── fixtures/
        │   ├── welcome.md
        │   └── clinic.md
        └── skills/
            └── usage.md
```

| 파일·디렉터리 | 여기서 개발하는 내용 |
| --- | --- |
| `config/settings.py` | 앱 등록, 데이터베이스, 기본 접근권한, 제공 인터페이스 설정 |
| `apps/sample/app.py` | 소스·처리 함수·실행 정책 연결 |
| `apps/sample/source/` | 기본 공급자 설정 또는 직접 만든 소스 연결 코드 |
| `apps/sample/fixtures/` | 로컬 예제 문서. 추가·수정한 뒤 동기화 |
| `apps/sample/skills/usage.md` | 앱 메타데이터로 소비자에게 전달할 사용 안내 |
| `manage.py` | 이 프로젝트의 명령 실행 |

자신의 폴더를 연결하려면 `apps/sample/source/local.py`의 경로를 수정하세요.
다른 서비스에 연결하려면 [Duru](https://github.com/imguno/duru)의 공급자를 설정하거나
소스 계약을 직접 구현합니다. 읽기·쓰기와 서비스별 API 호출은 소스 공급자가 담당합니다.

`apps/sample/app.py`는 해당 소스를 프레임워크에 연결합니다. 최소 구성은 다음과 같습니다.

```python
from galmuri import App
from .source.local import source

sample = App(name="sample", source=source)
```

처음에는 기본 처리로 시작하세요. 자체 파서, 변환 함수, 색인 방법이 필요해지면
앱 안에 구현하고 이곳에서 연결합니다.
[단계별 개발 예제](guides/build-an-integration.ko.md)에서 작성할 파일과
결과를 확인하는 방법을 안내합니다.

App 하나는 소스 연결 하나와 그 소스의 처리·검색·실행 정책을 묶습니다.
다른 소스를 추가하려면 `python manage.py startapp manuals`로 앱을 만들고,
소스를 설정한 다음 `APPS`에 `"apps.manuals.app:manuals"`를 추가하세요.
같은 프로젝트 안에서도 앱별로 처리 방식, 스케줄, 저장소를 다르게 지정할 수 있습니다.

## 무엇을 만들 수 있나요?

| 하고 싶은 일 | 구현하거나 설정하는 부분 |
| --- | --- |
| 사내 API에서 문서 가져오기 | Duru 공급자를 구현해 App에 연결 |
| 문서 형식을 통일하거나 메타데이터 추가 | 앱의 파싱·변환 함수 |
| LLM 클라이언트에 문서 제공 | MCP 인터페이스와 앱 사용 안내 |
| API나 자체 출력 형식 제공 | 기본 인터페이스 또는 직접 만든 출력 어댑터 |
| 임베딩 모델이나 벡터 저장소 교체 | 앱의 `RetrievalConfig` |
| 팀별 문서 접근권한 관리 | 계정·그룹·문서 권한 |

개발 예제에서 **익스포터**라고 부르는 출력 어댑터는 공통 `Service`를 통해
발행된 문서와 기능을 외부에 제공합니다. MCP·HTTP·gRPC·CLI 어댑터를 기본 제공하며,
직접 만든 어댑터는 `run()`을 구현해 `EXPOSURE_ADAPTERS`에 등록합니다.
임의의 외부 목적지로 자동 전송하고 재시도하는 기능은 이 어댑터 계약에 포함되지 않습니다.

RAG를 만든다면 Galmuri로 문서와 검색을 담당하는 쪽을 개발하세요.
기존 LLM 애플리케이션은 그 결과를 사용하고, 프롬프트·답변 생성·대화 로직을 담당합니다.

기존 `python -m galmuri new PATH`는 샘플 앱까지 등록된 프로젝트를 한 번에 만드는
단축 명령으로 계속 사용할 수 있습니다. `--process`·`--lexical`·`--retrieval` 프리셋도
유지됩니다. 키워드 검색·Qdrant 프리셋은 기본 계정 구성과 달리 신뢰하는 호스트에서
지정한 사용자 정보를 사용합니다.

## 문서 처리 커스터마이징

프로젝트 안에서 처리 함수를 수정할 수 있는 앱을 생성합니다.

```sh
python manage.py startapp articles --process
```

`APPS`에 `"apps.articles.app:articles"`를 등록하세요. 앱에는 다음 파일이 있습니다.

```text
apps/articles/
├── app.py
├── process.py
└── views/
    ├── __init__.py
    ├── normalization.py
    └── metadata.py
```

`views/normalization.py`에서 문서 내용 변환을 수정하세요.

```python
from dataclasses import replace

def normalize(documents):
    return tuple(
        replace(document, text=document.text.strip() + "\n")
        for document in documents
    )
```

`process.py`에서 이 함수와 예제의 메타데이터 함수를 연결합니다.

```python
from galmuri import Pipeline, Step
from .views.normalization import normalize
from .views.metadata import label

process = (
    Pipeline.default()
    .then(Step("normalize", process=normalize))
    .then(Step("label", process=label))
)
```

생성된 `app.py`의 `App(name="articles", source=source, process=process)`로
이 처리를 선택합니다. 함수는 실제 처리 작업을 실행할 때 호출됩니다.
`.then(Step(...))`으로 단계를 추가하거나 선언 순서를 바꿔 실행 순서를
조정하세요.

앱을 실행하고 처리 결과를 확인하세요.

```sh
python manage.py sync --app articles
python manage.py call search --app articles --mode lexical --query welcome
```

반환된 문서의 메타데이터에 `"pipeline": "articles"`가 포함됩니다.

위 추가 단계는 문서 튜플을 받아 문서 튜플을 반환합니다.
기본 파싱이 먼저 실행되고, 변환 후 문서 권한을 준비합니다.
전체 순서를 직접 구성하려면 `Pipeline(*steps)`에서
`file`, `documents`, 마지막 `result` 경계를 지정할 수 있습니다.
File을 받아 IngestResult를 반환하는 일반 함수도 `App(process=my_function)`으로
연결할 수 있습니다.
기본 처리와 `Pipeline`은 `retrieval`을 생략하면 자동 검색 구성을 유지합니다.
일반 함수인 커스텀 `process`/`handler`는 생략 시 키워드 검색만 사용하므로,
임베딩·벡터 색인을 사용하려면 `retrieval=RetrievalConfig()`를 명시하세요.
`IngestResult`를 직접 반환하는 함수는 문서 권한도 직접 지정해야 합니다.
설정의 기본 권한이 그 결과에 추가되지는 않습니다.

필요한 부분만 설정할 수 있습니다.

| App 옵션 | 용도 |
| --- | --- |
| `parser=ParsingConfig(process=my_parser)` | 파싱 함수 선택 |
| `ingestion=IngestConfig(...)` | 문서 권한 기본값 지정 |
| `retrieval=RetrievalConfig(...)` | 청킹·임베딩·저장소·검색 모드 선택 |
| `database=DatabaseConfig(...)` | DB 별칭과 선택적인 PostgreSQL 네임스페이스 지정 |
| `policy=SyncPolicy(...)` | 변경 확인 방식·주기·재시도 설정 |

위 Config 클래스는 `galmuri`에서,
`SyncPolicy`는 `galmuri.collection.policies`에서 import합니다.
예를 들어 `SyncPolicy(mode="scan", interval=86400)`은 하루에 한 번
전체 스캔을 예약합니다. 지정하지 않은 설정은 기본값을 사용합니다.

## 에이전트 스킬

앱 생성·처리 단계 수정·문서 접근 검사를 돕는
[using-galmuri](skills/using-galmuri/SKILL.md) 스킬을 제공합니다.
이 체크아웃에서 Codex용으로 설치할 수 있습니다.

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/using-galmuri "${CODEX_HOME:-$HOME/.codex}/skills/"
```

스킬 검색을 다시 불러오거나 앱을 재시작한 뒤 `$using-galmuri` 사용을 요청하세요.
호환되는 다른 에이전트에도 같은 스킬 폴더를 설치할 수 있습니다.
wheel에도 Python 설치의 데이터 디렉터리 아래
`share/galmuri/skills/using-galmuri` 경로로 포함됩니다.

## 소스·모델·저장소

| 구성요소 | 기본 제공 선택지 |
| --- | --- |
| 소스 | 로컬 파일, duru의 읽기 전용 Google Drive·Slack |
| 파서 | 텍스트, Markdown, Python 소스 |
| 임베딩 | 로컬 FastEmbed, OpenAI 임베딩 어댑터 |
| 청킹 | 구조를 따르는 기본 청커와 FastEmbed 토큰 한도, 명시적인 문자·커스텀 청커 |
| 벡터 저장소 | SQLite, PostgreSQL 정확 코사인 검색, Qdrant |
| 검색 | BM25 역색인, 벡터, 결합 방법을 바꿀 수 있는 하이브리드 |
| 문서·계정 저장소 | SQLite, PostgreSQL |

0.2.0부터 역색인 기반 키워드 검색과 구조를 따르는 기본 청커를 제공합니다.
한국어 검색의 한계, `SearchConfig`, 모델 입력 한도와 기존 프로젝트 갱신 방법은
[검색 설정·평가 안내](guides/search.ko.md)를 확인하세요.

인증 정보와 계정·폴더·채널 ID는 소스 라이브러리에 전달합니다.
`root_uri`가 있는 공급자는 `App.source`에 바로 넣고, 그 외에는
`galmuri.sources.resources.Resources(provider, root_uri)`로 연결하세요.
Google 기본 문서는 내보내기 형식을 명시해야 합니다.
Slack 메시지는 JSON 리소스로 들어오므로 필요한 필드를 선택하도록
파서를 커스터마이징할 수 있습니다.

현재 공급자 연결은 스냅샷을 스캔하고 버전을 비교합니다.
Google Drive·Slack의 네이티브 증분 피드를 자동 구독하지는 않습니다.

App에 `retrieval=RetrievalConfig(embedding=my_embedding, store=my_store,
mode="hybrid")`를 지정할 수 있습니다.
생략한 임베딩·저장소는 기본값으로 채우고, 기본 벡터 저장소는 App의 DB 선택을
따릅니다. `EmbeddingConfig(process=..., query_process=..., spec=...)`으로
문서 배치용·검색어용 함수 쌍을 연결할 수 있습니다.
기존 EmbeddingProvider·Chunker·VectorStore 구현체를 직접 넣어도 됩니다.

벡터 인덱싱을 끄려면 `retrieval=None`을 지정하세요.
기본 검색 모드를 키워드 검색으로 바꾸는 것만으로 벡터 생성이 꺼지지는 않습니다.
PostgreSQL 별칭·네임스페이스, Qdrant와 공급자 설정은
[설정·운영 상세 참조](guides/reference.md)를 확인하세요. 상세 참조는 영문입니다.

## 계정과 문서 접근권한

기본 또는 `--process`로 생성한 프로젝트에서 실행합니다.

```sh
python manage.py createsuperuser root
python manage.py serve http
```

첫 명령이 비밀번호를 요청합니다.
<http://127.0.0.1:8000/dashboard>에 로그인하면 계정·그룹·문서 권한과
개인 MCP 토큰을 관리할 수 있습니다. 기본 계정이나 비밀번호는 제공하지 않습니다.

기본 수집 처리와 문서 튜플로 끝나는 파이프라인은 생략한 `IngestConfig` 권한을
`config/settings.py`의 `DEFAULT_PERMISSIONS`에서 채웁니다.
생성된 기본값은 읽기·쓰기를 허용하며, 명시적인 빈 권한 목록은 접근을 거부합니다.
커스텀 처리 함수나 마지막 파이프라인 단계가 `IngestResult`를 반환하면
그 결과의 문서 권한을 직접 지정합니다. `Document`의 기본값인 빈 권한이
자동으로 공개 권한으로 바뀌지는 않습니다.
원본 쓰기 기능도 지원해야 하므로 읽기 전용 샘플에는 쓰기 도구가 노출되지 않습니다.

그룹 구성원 변경은 재인덱싱 없이 적용됩니다.
일반 관리자는 권한을 관리할 수 있고, root는 문서 ACL을 우회할 수도 있습니다.
root에도 토큰 범위·앱 제한·소스의 지원 기능과 버전 검사는 적용됩니다.

읽기 전용 계정 토큰을 생성하는 예제입니다.

```sh
python manage.py createuser reader
python manage.py mcp-token reader --scope read --app sample --token-file .runtime/reader.token
FRAMEWORK_TOKEN_FILE=.runtime/reader.token python manage.py serve mcp
```

로컬 계정 관리 명령은 프로젝트에 대한 신뢰할 수 있는 OS 접근권한이 필요합니다.
제한된 문서에는 검증된 자격증명으로 접근하며, 도구 인자로 사용자·그룹을
주장할 수 없습니다. 잘못되거나 만료·폐기된 자격증명은 거부됩니다.

## 앱 실행과 외부 연결

생성한 프로젝트에서 실행합니다.

| 명령 | 인터페이스 |
| --- | --- |
| `python manage.py serve http` | `/api/call`의 JSON API와 `/dashboard` 대시보드 |
| `python manage.py serve mcp` | 표준 입출력 기반 MCP |
| `python manage.py serve grpc` | Protobuf 서비스. 프레임워크 체크아웃의 `src/galmuri/exposure/grpc/exposure.proto`에 스키마 포함 |
| `python manage.py call describe --app sample` | 소스·검색 메타데이터를 반환하는 일회성 CLI 호출 |
| `python manage.py serve cli --workers 0` | 표준 입출력으로 JSON 명령 실행 |

`serve`는 기본적으로 스케줄러와 로컬 워커 하나를 시작합니다.
워커를 따로 실행하면 `--workers 0`을 지정하세요. MCP 어댑터는 stdio 서버입니다.
[통합 개발 튜토리얼](guides/build-an-integration.ko.md#rag-클라이언트-연결)에
stdio 클라이언트 등록 설정과 완전한 Python MCP 클라이언트 예제가 있습니다.
HTTP 배포에는 공개 HTTPS origin과 TLS 프록시가 필요하며,
생성된 루프백 HTTP 설정은 로컬 실행용입니다.

제공된 이미지는 프레임워크 체크아웃에서 빌드합니다.
나란히 있는 `duru/` 체크아웃이 필요합니다.

```sh
docker build --build-context duru=../duru -t galmuri-local .
docker run --rm galmuri-local --help
```

생성한 프로젝트를 `/workspace`에 마운트하면 코드와 상태를 유지할 수 있습니다.

## 명령어와 복구

생성한 프로젝트에서 실행합니다.
`BUILD_ID`는 인덱스 상태에서 확인한 빌드 ID로 바꾸세요.
상태 조회 같은 관리 호출에는 관리자 세션이 필요합니다. root 계정을 만든 뒤
`python manage.py login root --token-file .runtime/operator.token`으로 세션을
만드세요. 비밀번호를 요청합니다.

| 명령 | 용도 |
| --- | --- |
| `python manage.py sync` | 변경분 수집과 현재 실행 가능한 작업 처리 |
| `FRAMEWORK_TOKEN_FILE=.runtime/operator.token python manage.py call status` | root 세션으로 문서 작업과 처리 단계 확인 |
| `python manage.py index-status --app sample` | 벡터 생성 상태 확인 |
| `python manage.py index --drain` | 현재 실행 가능한 인덱싱 작업 처리 |
| `python manage.py reindex --app sample` | 새로운 벡터 세대 생성 예약 |
| `python manage.py index-retry BUILD_ID` | 실패한 벡터 생성 재시도 |
| `python manage.py activate` | 변경한 앱·파서·모델 설정 활성화 |
| `python manage.py scheduler` | 스케줄러 별도 실행 |
| `python manage.py worker` | 처리 워커 실행 |
| `python manage.py --help` | 전체 명령 확인 |

일반 Runtime 워커는 저장한 단계 결과 이후부터 재개합니다.
HTTP 원격 워커와 사용자 정의 워크플로는 전체 처리를 재시도합니다.
결과를 저장하기 전에 중단된 함수는 다시 실행될 수 있으므로,
외부 부수 효과가 있는 작업은 반복 실행에 안전하게 작성하세요.

문서 반영과 벡터 반영은 별도로 완료됩니다. 동기화 후 `index-status`를 확인하세요.
drain이 끝나도 향후 재시도나 실패한 작업이 남을 수 있습니다.
같은 구현의 동작을 바꾸면 revision을 올리고 활성화하세요.
이전 파서 연결로 만든 상태 DB도 `activate`가 필요할 수 있습니다.
자세한 복구·저장소 정리 명령은 [영문 상세 참조](guides/reference.md)를 확인하세요.

## 현재 제한

- 파이프라인은 선형 단계를 지원합니다. 분기·반복·DAG 스케줄러는 포함되어 있지 않습니다.
- Google Drive·Slack 공급자는 현재 읽기·메타데이터·목록 조회를 지원합니다.
  계정 API는 로컬 HTTP 예제로 테스트하며, 실제 서비스 계정 검증은 별도입니다.
- PDF/OCR 파서와 OpenSearch는 추가 구현이 필요합니다.
- SQLite는 단일 호스트용입니다. 여러 호스트의 문서·계정 상태를 공유하려면
  PostgreSQL을 사용하고, 각 프로세스에 호환되는 코드와 소스 설정을 적용하세요.
- SQLite·PostgreSQL 벡터 저장소는 정확 코사인 검색을 수행합니다.
  대규모 처리량·ANN 품질·장기 운영은 별도 평가가 필요합니다.

## 개발 참여

소스를 개발하려면 두 저장소를 나란히 내려받습니다.

```sh
git clone https://github.com/imguno/duru.git duru
git clone https://github.com/imguno/galmuri.git galmuri
cd galmuri
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ../duru -e '.[mcp,grpc,postgres,dev]'
python -m pytest -q
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m build --wheel
```

원격 DB 검사는 폐기 가능한 PostgreSQL의 주소를 `FRAMEWORK_POSTGRES_DSN`에
지정하면 실행됩니다. 실제 모델·LLM 검사는 일반 테스트와 별도로 실행합니다.
명령은 [영문 상세 참조](guides/reference.md#verify)를 확인하세요.

수정·확장 시 재현 가능한 예제와 관련 검증 결과를 함께 준비하세요.
사용자에게 보이는 동작을 바꾸면 영문·한글 README도 함께 갱신하세요.

[기여 안내](docs/CONTRIBUTING.ko.md), [보안 신고](docs/SECURITY.ko.md),
[배포 절차](docs/RELEASE.ko.md)도 확인하세요.

## 라이선스

[BSD 3-Clause 라이선스](LICENSE)를 사용합니다.
