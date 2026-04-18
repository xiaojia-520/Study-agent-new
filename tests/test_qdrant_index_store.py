import unittest
from unittest.mock import patch

from src.core.knowledge.query_filters import MetadataFilterClause, MetadataFilterSpec
from src.infrastructure.storage.qdrant_index_store import QdrantIndexStore


class FakeMetadataFilter:
    def __init__(self, *, key, value, operator):
        self.key = key
        self.value = value
        self.operator = operator


class FakeMetadataFilters:
    def __init__(self, *, filters, condition):
        self.filters = filters
        self.condition = condition


class FakeFilterCondition:
    AND = "AND"
    OR = "OR"


class FakeFilterOperator:
    EQ = "EQ"
    NE = "NE"


class QdrantIndexStoreTests(unittest.TestCase):
    def test_normalize_filters_converts_metadata_filter_spec(self) -> None:
        store = QdrantIndexStore()
        filters = MetadataFilterSpec(
            clauses=(
                MetadataFilterClause("course_id", "math-course"),
                MetadataFilterClause("lesson_id", "lesson-1", operator="ne"),
            )
        )

        with patch.object(
            store,
            "_load_metadata_filter_types",
            return_value=(FakeMetadataFilter, FakeMetadataFilters, FakeFilterCondition, FakeFilterOperator),
        ):
            normalized = store._normalize_filters(filters)

        self.assertIsInstance(normalized, FakeMetadataFilters)
        self.assertEqual(normalized.condition, "AND")
        self.assertEqual([(item.key, item.value, item.operator) for item in normalized.filters], [
            ("course_id", "math-course", "EQ"),
            ("lesson_id", "lesson-1", "NE"),
        ])

    def test_normalize_filters_keeps_foreign_filter_objects(self) -> None:
        store = QdrantIndexStore()
        sentinel = object()

        self.assertIs(store._normalize_filters(sentinel), sentinel)


if __name__ == "__main__":
    unittest.main()
