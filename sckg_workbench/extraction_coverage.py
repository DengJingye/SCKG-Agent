"""Explicit extraction selection accounting, never semantic completeness.

A linked block only has a claim anchor. It does not establish that every
scientific statement was extracted or that the claim is true or approved.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract
from .storage import content_hash


class BlockReference(Contract):
    ir_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)


class BlockDisposition(BlockReference):
    disposition: Literal['linked', 'partial', 'skipped']
    unit_indices: list[int] = Field(max_length=100)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def valid(self):
        if (not self.reason.strip() or len(self.unit_indices) != len(set(self.unit_indices))
                or any(index < 0 for index in self.unit_indices)):
            raise ValueError('Disposition needs a nonblank reason and distinct nonnegative unit indices')
        if (self.disposition == 'skipped') != (not self.unit_indices):
            raise ValueError('Only skipped blocks have no linked units')
        return self


class ExtractionCoverage(Contract):
    scope_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    entries: list[BlockDisposition] = Field(min_length=1, max_length=256)


def build_extraction_scope(documents, required_blocks):
    """Freeze exact blocks already in the selected immutable input documents."""
    if not isinstance(required_blocks, list) or not 1 <= len(required_blocks) <= 256:
        raise ValueError('Required extraction blocks must contain 1 to 256 explicit references')
    refs = [BlockReference.model_validate(item).model_dump(mode='json') for item in required_blocks]
    pairs = [(row['ir_id'], row['block_id']) for row in refs]
    if len(set(pairs)) != len(pairs):
        raise ValueError('Required extraction blocks must be distinct')
    available = {(row['document']['id'], block['id']): block['exact_text']
                 for row in documents for block in row['document']['blocks']}
    if any(pair not in available for pair in pairs):
        raise ValueError('Required extraction block is outside the prepared input')
    scope = {'schema_version': 'explicit-extraction-block-scope-v1',
             'blocks': [{**ref, 'text_sha256': hashlib.sha256(available[pair].encode()).hexdigest()}
                        for ref, pair in zip(refs, pairs)],
             'meaning': 'Block-to-claim linkage accounting only; semantic completeness and truth not established.'}
    return {**scope, 'scope_hash': content_hash(scope)}


def validate_extraction_coverage(scope, output, coverage):
    """Require every declared block disposition and bind it to actual anchors."""
    if not scope:
        if coverage is not None:
            raise ValueError('Coverage was not declared in this extraction input')
        return None
    if coverage is None:
        raise ValueError('Declared extraction scope requires explicit block coverage')
    if scope.get('scope_hash') != content_hash({k: v for k, v in scope.items() if k != 'scope_hash'}):
        raise ValueError('Extraction scope hash changed')
    value = ExtractionCoverage.model_validate(coverage).model_dump(mode='json')
    if value['scope_hash'] != scope['scope_hash']:
        raise ValueError('Coverage must bind the exact prepared extraction scope')
    required = {(b['ir_id'], b['block_id']) for b in scope['blocks']}
    rows = {(r['ir_id'], r['block_id']): r for r in value['entries']}
    if len(rows) != len(value['entries']) or set(rows) != required:
        raise ValueError('Coverage must account for every required block exactly once')
    actual = {pair: set() for pair in required}
    for index, unit in enumerate(output['units']):
        for anchor in unit['anchors']:
            pair = (anchor['ir_id'], anchor['block_id'])
            if pair not in actual:
                raise ValueError('Claim anchor is outside the declared extraction block scope')
            actual[pair].add(index)
    for pair, row in rows.items():
        if set(row['unit_indices']) != actual[pair]:
            raise ValueError('Block disposition must identify all and only its actual anchored units')
    return {'schema_version': 'explicit-extraction-block-accounting-v1', **value,
            'disposition_counts': dict(Counter(row['disposition'] for row in value['entries'])),
            'semantic_completeness_established': False,
            'scientific_truth_established': False,
            'human_review_established': False,
            'coverage_hash': content_hash(value)}
