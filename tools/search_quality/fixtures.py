"""Versioned examples with relevance judgments fixed before running either ranker.

These small hand-authored judgments demonstrate behaviors; they are not a
representative relevance benchmark. Near-matches are deliberately included so
recall gains cannot hide precision losses.
"""

from dataclasses import dataclass

FIXTURE_REVISION = "bilingual-v1"


@dataclass(frozen=True)
class Query:
    name: str
    text: str
    relevant: tuple[str, ...]
    behavior: str


DOCUMENTS = {
    "ko-storage": "저장소 연결 방법: 주소를 입력하고 연결을 확인합니다.",
    "ko-document": "문서를 등록하는 방법: 파일을 선택하고 등록합니다.",
    "ko-permissions": "접근권한 설정 안내: 읽기와 쓰기를 지정합니다.",
    "ko-index": "색인 관리 방법: 새로운 자료를 반영합니다.",
    "ko-card-payment": "카드결제 승인 방법: 거래 상태를 확인합니다.",
    "ko-card-loss": "카드분실 신고 방법: 분실 사실을 접수합니다.",
    "ko-bank-payment": "계좌결제 승인 방법: 은행에서 거래 상태를 확인합니다.",
    "ko-refund-policy": "환불정책 안내: 구매 후 취소 기한을 설명합니다.",
    "ko-failure-cause": "실패원인 안내: 오류 보고서의 원인을 설명합니다.",
    "en-cat": "cat command displays file contents.",
    "en-concatenate": "concatenate concatenate concatenate joins multiple strings.",
    "en-category": "category category category organizes labels.",
    "en-user-id": "user_id stores the unique principal identifier.",
    "en-user-name": "user_name stores a display label.",
    "en-vector-database": "A vector database stores embeddings for similarity lookup.",
    "en-vector-art": "A vector drawing uses geometric paths for illustrations.",
    "en-database-migration": "A database migration updates table schemas.",
    "en-rare-short": "ordinary quasar: a compact astronomical explanation.",
    "en-rare-repetition": "ordinary quasar " * 40 + "filler " * 160,
    "en-accent": "Straße is the German spelling used on this street label.",
}

QUERIES = (
    Query(
        "particle-in-query", "저장소를", ("ko-storage",), "A query particle is absent in source."
    ),
    Query("particle-in-document", "문서", ("ko-document",), "Source has an attached particle."),
    Query("spaced-query", "접근 권한", ("ko-permissions",), "Query splits a source compound."),
    Query("joined-query", "색인관리", ("ko-index",), "Query joins source words."),
    Query(
        "hangul-near-matches",
        "카드결제",
        ("ko-card-payment",),
        "Related syllables must not hide unrelated payment/lost-card results.",
    ),
    Query(
        "absent-hangul-compound",
        "환불실패",
        (),
        "Neither refund policy nor general failure causes answers refund failure.",
    ),
    Query("english-word", "cat", ("en-cat",), "An exact word competes with repeated substrings."),
    Query(
        "compound-identifier",
        "user_id",
        ("en-user-id",),
        "An exact identifier competes with another identifier sharing its first component.",
    ),
    Query(
        "two-word-topic",
        "vector database",
        ("en-vector-database",),
        "Both query concepts are needed; single-concept articles are negatives.",
    ),
    Query(
        "rare-and-common",
        "ordinary quasar",
        ("en-rare-short",),
        "A concise answer competes with repeated terms and common-term distractors.",
    ),
    Query(
        "rare-term-length",
        "quasar",
        ("en-rare-short",),
        "A concise explanation is relevant; repeated-term filler is not.",
    ),
    Query("unicode-casefold", "STRASSE", ("en-accent",), "Unicode casefold exact-word match."),
    Query("absent-english", "hyperbolicneedle", (), "A completely absent English term."),
)


def corpus(distractors: int) -> dict[str, str]:
    documents = dict(DOCUMENTS)
    for number in range(distractors):
        documents[f"distractor-{number:06}"] = (
            f"ordinary inventory ledger reference {number}. "
            "Shipping schedules and warehouse observations. 배송 일정과 창고 기록. "
            + "routine warehouse observation "
            * (1 + number % 8)
        )
    return documents
