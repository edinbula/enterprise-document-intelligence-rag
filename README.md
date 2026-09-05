# Enterprise Document Intelligence and Hybrid RAG

A cost-safe portfolio implementation of an enterprise document-processing and
retrieval-augmented generation platform using Python, AWS-compatible object
storage, Databricks, Delta Lake, and hybrid retrieval.

**Development version:** `0.1.0.dev0`

## Objectives

The project demonstrates how an enterprise platform can:

- Ingest PDF, DOCX, CSV, and scanned documents.
- Preserve document identity, versions, metadata, and page references.
- Store source documents through an S3-compatible interface.
- Transform raw documents into Bronze, Silver, and Gold datasets.
- Support keyword, vector, and hybrid retrieval.
- Generate grounded answers with source citations.
- Refuse answers when retrieved evidence is insufficient.
- Measure retrieval and answer quality.
- Protect document access boundaries.

## Zero-cost development policy

This project has a hard zero-cost cloud requirement.

- Local development uses free and open-source tools.
- Synthetic documents are used exclusively.
- Databricks work runs within Free Edition quotas.
- AWS use is limited to the protected AWS Free plan.
- No paid account upgrade is required.
- No infrastructure deployment may occur without an explicit cost review.
- Credentials, account identifiers, and secrets must never enter Git.

## Planned architecture

1. Local or AWS S3-compatible source storage.
2. Document parsing, OCR fallback, normalization, and deduplication.
3. Bronze, Silver, and Gold Delta datasets.
4. Embedding generation and hybrid retrieval.
5. Grounded RAG API with citations and access filtering.
6. Evaluation using Recall@K, MRR, groundedness, and citation checks.

Databricks Free Edition does not support custom workspace storage locations.
Therefore, the free portfolio implementation demonstrates AWS S3 and
Databricks using separate adapters while retaining a production-oriented
interface for future direct integration.

## Status

Phase 0: repository and engineering foundation.
