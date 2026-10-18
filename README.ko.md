# 갈무리 (Galmuri)

[English](README.md) · 한국어

문서 소스를 연결하고, 검색 가능한 문서로 가공한 뒤 MCP·HTTP·gRPC·CLI로
RAG 애플리케이션에 제공하는 Python 프레임워크입니다.

로컬 폴더와 기본 샘플 앱으로 시작할 수 있습니다. 필요한 부분에 파서,
문서 변환 함수, 임베딩 모델, 벡터 저장소를 연결하세요.
RAG 애플리케이션은 제공되는 문서·검색 API를 이용해 답변을 구성합니다.

**현재 상태:** 개발자 프리뷰입니다. 패키지와 import 이름은 `galmuri`이며,
명령은 `galmuri` 또는 `python -m galmuri`입니다. 소스 접근에는 독립 라이브러리
`duru`를 사용합니다.

## 목차

- [활용 예시](#활용-예시)
- [빠른 시작](#빠른-시작)
- [생성되는 프로젝트](#생성되는-프로젝트)
- [문서 처리 커스터마이징](#문서-처리-커스터마이징)
- [에이전트 스킬](#에이전트-스킬)
- [소스·모델·저장소](#소스모델저장소)
- [계정과 문서 접근권한](#계정과-문서-접근권한)
- [앱 실행과 외부 연결](#앱-실행과-외부-연결)
- [명령어와 복구](#명령어와-복구)
- [현재 제한](#현재-제한)
- [개발 참여](#개발-참여)

## 활용 예시

| 하고 싶은 일 | 시작 방법 |
| --- | --- |
| 로컬 폴더의 문서를 MCP 클라이언트로 검색 | 기본 샘플 앱을 만든 뒤 `serve mcp` 실행 |
| 검색 반영 전에 문서를 정제하거나 메타데이터 추가 | `new PATH --process`로 생성하고 `views/` 수정 |
| Google Drive나 Slack 문서 읽기 | duru 공급자에 인증 정보와 대상 ID 전달 |
| 다른 임베딩 모델이나 벡터 저장소 사용 | App의 `RetrievalConfig` 지정 |
| 팀별로 문서 접근권한 관리 | 대시보드의 계정·그룹·문서 권한 사용 |
| 여러 프로세스가 같은 상태를 사용 | PostgreSQL과 호환되는 앱·계정 설정 사용 |

텍스트·Markdown·Python 소스 파서를 제공합니다.
기본 샘플은 로컬 다국어 임베딩과 SQLite 벡터 저장소를 사용합니다.

## 빠른 시작

**Python 3.12 이상**이 필요합니다. 배포 대상은 Linux이며, Dockerfile은
Python 3.13을 사용합니다. 로컬 체크아웃을 다음처럼 준비하세요.

```text
workspace/
├── access/     # duru 체크아웃
└── project/    # 프레임워크 체크아웃
```

`workspace/`에서 실행합니다.

```sh
cd project
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ../access -e '.[mcp,grpc]'

python -m galmuri new ./example
cd example
python manage.py sync
python manage.py call search --app sample --mode lexical --query welcome
python manage.py serve http
```

샘플에는 `welcome.md`와 `clinic.md`가 있습니다.
동기화하면 문서가 반영되고, 검색 명령은 일치하는 문서 데이터를 반환합니다.
<http://127.0.0.1:8000/dashboard>에서 문서를 탐색할 수 있습니다.
서버는 Ctrl+C로 종료합니다.

처음 임베딩할 때 모델 가중치를 다운로드합니다.
기존 캐시를 재사용하거나 캐시를 유지하려면 동기화 전에 `EMBEDDING_CACHE`를
지정하세요. 기본 로컬 모델에는 LLM API 키가 필요하지 않습니다.

생성한 프로젝트에서 의미 검색을 실행할 수 있습니다.

```sh
python manage.py call search --app sample --mode vector --query "Where should I go when I feel unwell?"
```

## 생성되는 프로젝트

기본 App은 별도의 읽기 함수나 파서 구현 없이 소스를 연결합니다.

```python
# apps/sample/app.py
from galmuri import App
from .source.local import source

sample = App(name="sample", source=source)
```

| 파일·디렉터리 | 여기서 수정하는 내용 |
| --- | --- |
| `config/settings.py` | 활성화할 앱, DB 연결, 기본 접근권한, 서버 옵션 |
| `apps/sample/app.py` | 문서 소스와 선택적인 처리·검색 설정 |
| `apps/sample/source/local.py` | 읽어올 폴더나 공급자 |
| `apps/sample/fixtures/` | 샘플 파일. 파일을 추가·수정한 뒤 동기화 |
| `apps/sample/skills/usage.md` | 앱 메타데이터로 전달할 사용 안내 |
| `manage.py` | 프로젝트 명령어 진입점 |

다른 폴더를 연결하려면 `apps/sample/source/local.py`의
`ReadOnlyLocalProvider` 경로를 바꾸세요.
샘플은 읽기 전용이며, 클라이언트에서 원본을 수정하려면 조건부 쓰기를
지원하는 소스를 사용해야 합니다.

새 디렉터리를 만들 때 프리셋을 선택할 수 있습니다.

| 명령 | 생성되는 예제 |
| --- | --- |
| `python -m galmuri new PATH` | 로컬 소스, 기본 처리, 계정, 로컬 임베딩·벡터 |
| `python -m galmuri new PATH --process` | 기본 구성과 실행 가능한 문서 변환 함수 |
| `python -m galmuri new PATH --lexical` | 처리 함수를 직접 지정하는 키워드 검색 튜토리얼 |
| `python -m galmuri new PATH --retrieval` | Qdrant 설정과 Compose 파일 |

프리셋은 함께 지정할 수 없습니다.
키워드 검색·Qdrant 튜토리얼은 기본 계정 구성과 달리,
신뢰하는 호스트에서 지정한 사용자 정보를 사용합니다.

## 문서 처리 커스터마이징

프레임워크 체크아웃에서 실행 가능한 처리 예제를 생성합니다.

```sh
python -m galmuri new ./custom-example --process
```

샘플 앱에 다음 파일이 추가됩니다.

```text
apps/sample/
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

생성된 `app.py`의 `App(name="sample", source=source, process=process)`로
이 처리를 선택합니다. 함수는 실제 처리 작업을 실행할 때 호출됩니다.
`.then(Step(...))`으로 단계를 추가하거나 선언 순서를 바꿔 실행 순서를
조정하세요.

위 추가 단계는 문서 튜플을 받아 문서 튜플을 반환합니다.
기본 파싱이 먼저 실행되고, 변환 후 문서 권한을 준비합니다.
전체 순서를 직접 구성하려면 `Pipeline(*steps)`에서
`file`, `documents`, 마지막 `result` 경계를 지정할 수 있습니다.
File을 받아 IngestResult를 반환하는 일반 함수도 `App(process=my_function)`으로
연결할 수 있습니다.

필요한 부분만 설정할 수 있습니다.

| App 옵션 | 용도 |
| --- | --- |
| `parser=ParsingConfig(process=my_parser)` | 파싱 함수 선택 |
| `ingestion=IngestConfig(...)` | 문서 권한 기본값 지정 |
| `retrieval=RetrievalConfig(...)` | 청킹·임베딩·저장소·검색 모드 선택 |
| `database=DatabaseConfig(...)` | DB 별칭과 선택적인 PostgreSQL 네임스페이스 지정 |
| `policy=SyncPolicy(...)` | 변경 확인 방식·주기·재시도 설정 |

위 Config 클래스는 `framework`에서,
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
| 청킹 | 문자 청커, 직접 구현한 Chunker, `ChunkingConfig(process=...)` |
| 벡터 저장소 | SQLite, PostgreSQL 정확 코사인 검색, Qdrant |
| 검색 | 키워드, 벡터, 하이브리드 |
| 문서·계정 저장소 | SQLite, PostgreSQL |

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

권한을 생략하면 `config/settings.py`의 `DEFAULT_PERMISSIONS`를 따릅니다.
생성된 기본값은 읽기·쓰기를 허용하며, 명시적인 빈 권한 목록은 접근을 거부합니다.
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
HTTP 배포에는 공개 HTTPS origin과 TLS 프록시가 필요하며,
생성된 루프백 HTTP 설정은 로컬 실행용입니다.

제공된 이미지는 프레임워크 체크아웃에서 빌드합니다.
나란히 있는 `access/` 체크아웃이 필요합니다.

```sh
docker build --build-context duru=../access -t galmuri-local .
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

프레임워크 체크아웃에서 실행합니다.

```sh
python -m pip install -e ../access -e '.[mcp,grpc,postgres,dev]'
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

[기여 안내](CONTRIBUTING.ko.md), [보안 신고](SECURITY.ko.md),
[변경 기록](CHANGELOG.ko.md), [배포 절차](RELEASE.ko.md)도 확인하세요.

## 라이선스

[BSD 3-Clause 라이선스](LICENSE)를 사용합니다.
