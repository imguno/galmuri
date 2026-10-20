# 검색 설정과 품질 평가

[English](search.md) · 한국어 · [README](../README.ko.md)

이 가이드는 **Galmuri 0.2.0** 기준입니다. 0.1.0은 부분 문자열 검색과
문자 단위 기본 청킹을 사용했습니다. 기존 환경을 갱신하기 전에
[업그레이드 절차](#기존-프로젝트-갱신)를 확인하세요.

## 기본 동작

소스만 지정한 App도 그대로 사용할 수 있습니다. 키워드 검색은 SQLite와
PostgreSQL 모두 역색인과 BM25를 사용합니다. 문서 발행·갱신·철회와 같은
트랜잭션에서 색인을 갱신합니다. 검색할 때 전체 문서 본문을 Python으로
가져오지 않고, 일치하는 색인을 순위화한 뒤 접근 가능한 후보의 본문만 읽습니다.

Unicode NFKC 정규화와 대소문자 정규화를 적용합니다. `user_id` 같은 식별자는
하나의 단어로 유지하며 단어 검색어는 모두 일치해야 합니다. 한국어는 공백을
연결한 한글 음절 bigram 중 검색어의 서로 다른 bigram 절반 이상이 일치해야 합니다.
일부 조사·띄어쓰기 차이를 허용하지만 **형태소 분석은 아닙니다**.
부분 일치와 오탐은 여전히 생길 수 있습니다. 빈 검색어와 구두점만 있는 검색어는
결과를 반환하지 않습니다. 검색어는 최대 4,096자, 분석된 토큰은 최대 128개입니다.

짧은 단어에 긴 조사가 붙으면 놓칠 수 있습니다. 예를 들어 본문에 `문서`만 있으면
`문서에서` 검색과 일치하지 않을 수 있습니다. 실제 업무 질의로 평가해야 하며,
이 기본값이 한국어 형태소 수준의 재현율을 보장하지는 않습니다.

BM25 통계는 접근 불가능한 문서를 포함한 App의 활성 문서 집합에서 계산합니다.
반환되는 본문은 현재 권한으로 제한됩니다. 점수는 상대적인 순위이며
정답 확률이나 신뢰도가 아닙니다. 벡터 검색의 세대·권한 검사는 별도로 유지됩니다.

## 검색 방법 교체

```python
from galmuri import App
from galmuri.retrieval import RetrievalConfig, SearchConfig, ReciprocalRankFusion
from .source.local import source

sample = App(
    name="sample",
    source=source,
    retrieval=RetrievalConfig(
        mode="hybrid",
        search=SearchConfig(
            fusion=ReciprocalRankFusion(k=20, lexical_weight=2, vector_weight=1),
            candidate_limit=200,
        ),
    ),
)
```

기본 결합은 동일 가중치의 RRF이며 `k=60`입니다. 하이브리드는 검색기마다
`min(candidate_limit, max(64, 4 * limit))`개 후보를 사용합니다.
후보 상한은 1–1,000이며 실제 반환 수를 제한할 수 있습니다.
검색 정책만 바꾸면 임베딩을 다시 만들지 않습니다.

별도 검색기도 함수로 연결할 수 있습니다.

```python
from galmuri.retrieval import SearchCandidate, SearchConfig

def lookup(query, *, app, limit):
    hits = external_index.search(app=app, query=query, limit=limit)
    return tuple(SearchCandidate(hit.document_key, hit.score) for hit in hits)

search = SearchConfig(lexical=lookup)
```

`external_index`는 직접 구성한 클라이언트입니다. 해당 App에 발행된 문서 ID와
유한한 점수를 내림차순으로, 중복 없이 `limit`개 이하 반환하세요.
알 수 없거나 권한이 없는 ID로 본문을 가져갈 수는 없습니다.
외부 색인의 수집·갱신·삭제는 어댑터가 관리해야 합니다.
접근 불가능한 후보도 외부 검색기의 후보 수를 차지할 수 있으므로 검색 범위를 조정하세요.
후보에는 ID와 점수가 있고 외부 색인의 세대 정보는 없습니다. Galmuri는 현재 권한으로
현재 발행된 본문을 읽지만, 외부 점수가 그 버전에서 계산됐는지는 증명할 수 없습니다.
외부 색인의 최신성은 어댑터가 관리해야 하며, 본문·권한 검사가 오래된 순위를 보정하지는 않습니다.

`fusion=`에도 함수를 넣을 수 있습니다. `lexical`과 `vector` 후보 튜플이 담긴
읽기 전용 매핑을 받고, 그 안의 문서 ID로 구성된 후보를 점수 내림차순으로
반환합니다. 문서 본문은 전달되지 않습니다. 함수나 지연 생성기의 실행이 끝난 뒤
현재 권한·원본 변경·벡터 세대를 다시 확인합니다.
계약을 어긴 반환값은 명시적으로 실패합니다. `describe`에서 실제 검색 정책을 확인하세요.

## 청크와 임베딩

기본 청크는 Markdown 제목·문단·코드 블록 경계를 존중하고 큰 블록만 분할합니다.
문서 ID와 권한은 유지하며 청크 위치는 저장된 원문을 그대로 가리킵니다.
전체 CommonMark AST를 구현한 파서는 아닙니다.

FastEmbed와 기본 청커를 쓰면 실제 모델 토크나이저의 복사본으로 토큰 수를
확인하고 입력 한도를 넘는 청크를 더 나눕니다. 특수 토큰도 계산합니다.
모델 로딩은 App 설정 때가 아니라 인덱싱할 때 발생합니다.
직접 구현한 `Chunker`·`ChunkingConfig`와 명시적인 `CharacterChunker`도 계속 지원합니다.
직접 토크나이저를 연결할 때는
`TokenBudgetChunker(base, count_tokens, max_tokens, identity="your-tokenizer-v1")`를
사용할 수 있습니다. 카운터는 잘리지 않은 전체 입력과 접두사·특수 토큰을 계산해야 합니다.

FastEmbed는 명시한 청커의 출력이나 검색어가 너무 길면 뒷부분을 조용히 버리지 않고
오류를 반환합니다. 실패한 인덱싱 작업을 확인하고 청킹 설정을 고친 뒤 활성화·재색인하세요.
다른 임베딩 어댑터의 입력 한도 처리는 해당 어댑터의 책임입니다.

가벼운 기본 모델은 다국어 MiniLM-L12를 유지합니다. 384차원이며 입력 한도는
128토큰이므로 문자 수만으로 청크 크기를 정하면 부족합니다.
[공식 모델 정보](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
모델은 `RetrievalConfig(embedding=...)`로 바꾸고 실제 문서로 품질·메모리·지연을 비교하세요.
E5-large를 사용할 때는 필요한 접두사를 명시합니다.

```python
from galmuri.retrieval import FastEmbedEmbedding, RetrievalConfig

retrieval = RetrievalConfig(
    embedding=FastEmbedEmbedding(
        "intfloat/multilingual-e5-large",
        passage_prefix="passage: ",
        query_prefix="query: ",
    ),
)
```

접두사도 임베딩 식별값에 포함됩니다. E5-large는 MiniLM보다 메모리가 훨씬 많이
필요하며, 차원이 크다고 사용자 문서에서 더 좋은 결과가 보장되지는 않습니다.
[E5 사용 조건](https://huggingface.co/intfloat/multilingual-e5-large).

## 기존 프로젝트 갱신

서버와 워커를 함께 중단하고 상태 저장소를 백업하세요. 이전·새 버전 워커를
섞어 실행하는 갱신은 지원하지 않습니다. 첫 실행은 메타데이터 쓰기 잠금을 잡고
기존 문서의 키워드 색인을 한 번 구성하므로 문서가 많으면 시작이 늦어질 수 있습니다.
기본 파서와 청커 식별값도 변경되었습니다.

```sh
python manage.py activate
python manage.py sync
python manage.py index-status
```

문서 처리와 벡터 작업이 완료된 뒤 서비스를 재개하세요. 남은 작업이 있으면
워커를 실행합니다. 명시적으로 선택한 청커의 식별값은 유지되며,
검색 정책만 변경할 때는 임베딩 재생성이 필요하지 않습니다.

## 품질 측정

소스 체크아웃에서 다음 명령을 실행하세요.

```sh
python -m tools.search_quality \
  --output .verification/search-quality.json \
  --documents 100 1000 3000
```

고정한 한국어·영어 합성 문서를 정상 Runtime 경로로 발행하고 지정한 수의
방해 문서를 추가합니다. 이전 부분 문자열 검색과 결과를 비교해 개별 순위,
양성 질의의 Top1·MRR@3, 부재 질의 오탐, 반복 실행 중앙 시간을 기록합니다.
문서가 적으면 색인이 더 느릴 수도 있습니다.
한국어 전체 성능이나 모델 우열을 증명하는 벤치마크가 아니라 회귀 확인 도구입니다.
서비스 도메인의 문서·질의·정답 평가는 따로 준비하세요.
