"""
Pydantic Schemas untuk API.

Berisi:
- Hasil analisis (AuditResultItem, AnalyzeResponse, dll.)
- Preview & Tree (PreviewNode, PreviewResponse, dll.)
- Settings (RuntimeSettingsResponse, RuntimeSettingsUpdate, dll.)
- Audit Workflow (BulkUpdateRequest, AddItemRequest, DeleteItemsRequest, BulkActionResponse)
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.prompts.aspects import STATUS_KEPATUHAN_DEFAULT


# ---------------------------------------------------------------------------
# Hasil analisis
# ---------------------------------------------------------------------------

class AuditResultItem(BaseModel):
    # AI (7 field)
    referensi_regulasi: str = ""
    aspek: str = ""
    bab_pasal_ayat: str = ""
    point_ketentuan: str = ""
    pemeriksaan: str = ""
    metode_audit: str = ""
    kebutuhan_bukti: str = ""

    # Auditor (2 field)
    status_kepatuhan: str = STATUS_KEPATUHAN_DEFAULT
    catatan_temuan: str = ""

    # Internal (tidak ke Excel)
    is_valid: bool = True
    validation_notes: list[str] = Field(default_factory=list)


class ChunkError(BaseModel):
    lampiran: str | None = None
    bab: str | None = None
    pasal: str | None = None
    ayat: str | None = None
    error: str
    affected_count: int = 1


class AnalyzeResponse(BaseModel):
    result_id: str
    filename: str
    preview_id: str = ""

    total_chunks: int
    total_chunks_available: int = 0
    total_batches: int
    total_ketentuan: int
    total_valid: int
    total_flagged: int

    results: list[AuditResultItem]
    chunk_errors: list[ChunkError] = Field(default_factory=list)
    total_by_aspect: dict[str, int] = Field(default_factory=dict)
    filter_applied: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Edit single item
# ---------------------------------------------------------------------------

class UpdateItemRequest(BaseModel):
    aspek: str | None = None
    bab_pasal_ayat: str | None = None
    point_ketentuan: str | None = None
    pemeriksaan: str | None = None
    metode_audit: str | None = None
    kebutuhan_bukti: str | None = None
    status_kepatuhan: str | None = None
    catatan_temuan: str | None = None


# ---------------------------------------------------------------------------
# Audit Workflow — Bulk / Add / Delete
# ---------------------------------------------------------------------------

class BulkUpdateRequest(BaseModel):
    """
    Payload untuk PATCH /api/results/{id}/items/bulk.
    Update kolom auditor (status + catatan) untuk banyak item sekaligus.
    """
    item_indices: list[int] = Field(..., min_length=1)
    status_kepatuhan: str | None = None
    catatan_temuan: str | None = None


class AddItemRequest(BaseModel):
    """
    Payload untuk POST /api/results/{id}/items.
    Tambah baris manual ke hasil analisis (di luar output AI).
    """
    referensi_regulasi: str = ""
    aspek: str = ""
    bab_pasal_ayat: str = ""
    point_ketentuan: str = ""
    pemeriksaan: str = ""
    metode_audit: str = ""
    kebutuhan_bukti: str = ""
    status_kepatuhan: str = STATUS_KEPATUHAN_DEFAULT
    catatan_temuan: str = ""


class DeleteItemsRequest(BaseModel):
    """Payload untuk DELETE /api/results/{id}/items (body, bukan path)."""
    item_indices: list[int] = Field(..., min_length=1)


class BulkActionResponse(BaseModel):
    """Response generik untuk bulk update / delete / add."""
    affected: int
    total_ketentuan: int
    total_valid: int
    total_flagged: int
    total_by_aspect: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Preview & Tree
# ---------------------------------------------------------------------------

class PreviewNode(BaseModel):
    id: str
    label: str
    type: str
    page_start: int | None = None
    page_end: int | None = None
    chunk_indices: list[int] = Field(default_factory=list)
    children: list["PreviewNode"] = Field(default_factory=list)


PreviewNode.model_rebuild()


class PreviewResponse(BaseModel):
    preview_id: str
    filename: str
    total_chunks: int
    tree: list[PreviewNode]
    from_cache: bool = False     
    parse_time_ms: int = 0


class PreviewRetrieveResponse(BaseModel):
    preview_id: str
    filename: str
    total_chunks: int
    tree: list[PreviewNode]
    filter_applied: list[str] = Field(default_factory=list)


class AnalyzeSelectedRequest(BaseModel):
    preview_id: str
    selected_chunk_indices: list[int] = Field(..., min_length=1)
    selected_labels: list[str] = Field(default_factory=list)
    nama_regulasi: str | None = None


# ---------------------------------------------------------------------------
# Estimasi Biaya
# ---------------------------------------------------------------------------

class EstimateRequest(BaseModel):
    preview_id: str
    selected_chunk_indices: list[int] = Field(..., min_length=1)


class EstimateResponse(BaseModel):
    total_chunks: int
    total_chars: int
    estimated_batches: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    cost_idr: float
    time_seconds_estimate: int
    model_name: str


# ---------------------------------------------------------------------------
# Runtime Settings
# ---------------------------------------------------------------------------

class RuntimeSettingsResponse(BaseModel):
    """Response GET /api/settings — API key di-mask."""
    gemini_api_key_masked: str = ""
    gemini_api_key_set: bool = False
    gemini_model: str = ""
    gemini_max_output_tokens: int = 8192
    gemini_min_seconds_between_requests: float = 4.5
    max_chars_per_batch: int = 6000
    theme: str = "auto"
    preset_models: list[str] = Field(default_factory=list)


class RuntimeSettingsUpdate(BaseModel):
    """Payload PUT /api/settings."""
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    gemini_max_output_tokens: int | None = None
    gemini_min_seconds_between_requests: float | None = None
    max_chars_per_batch: int | None = None
    theme: str | None = None


class ConnectionTestRequest(BaseModel):
    """Payload POST /api/settings/test-connection."""
    api_key: str | None = None
    model: str | None = None


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    model_tested: str
    latency_ms: int = 0


class DiagnosticsResponse(BaseModel):
    server_ok: bool
    ai_ok: bool
    ai_message: str
    model_name: str
    cache_previews_count: int
    cache_size_mb: float
    outputs_count: int
    app_version: str
    app_env: str

    # ---------------------------------------------------------------------------
# Gap Analysis Tool
# ---------------------------------------------------------------------------

class RequirementItem(BaseModel):
    """Satu baris persyaratan di Gap Analysis."""
    persyaratan: str = ""
    referensi: str = ""
    catatan: str = ""
    status_gap: str = ""  # kosong default, diisi auditor


class AnalyzeRequirementsRequest(BaseModel):
    """Payload POST /api/analyze-requirements."""
    preview_id: str
    nama_regulasi: str | None = None
    # Kalau kosong → analisis semua chunk. Kalau diisi → hanya chunk
    # yang cocok dengan filter teks (case-insensitive substring).
    filter_text: str | None = None


class AnalyzeRequirementsResponse(BaseModel):
    result_id: str
    filename: str
    preview_id: str = ""

    total_chunks_analyzed: int
    total_chunks_available: int
    total_batches: int
    total_requirements: int

    requirements: list[RequirementItem]
    chunk_errors: list[ChunkError] = Field(default_factory=list)
    filter_applied: str = ""


class UpdateRequirementRequest(BaseModel):
    """Payload PATCH /api/requirements/{id}/items/{idx}."""
    persyaratan: str | None = None
    referensi: str | None = None
    catatan: str | None = None
    status_gap: str | None = None


class AddRequirementRequest(BaseModel):
    """Payload POST /api/requirements/{id}/items."""
    persyaratan: str = ""
    referensi: str = ""
    catatan: str = ""
    status_gap: str = ""


class DeleteRequirementsRequest(BaseModel):
    """Payload DELETE /api/requirements/{id}/items."""
    item_indices: list[int] = Field(..., min_length=1)


class RequirementsBulkActionResponse(BaseModel):
    affected: int
    total_requirements: int

    # ---------------------------------------------------------------------------
# Prompt Editor
# ---------------------------------------------------------------------------

class PromptStatusResponse(BaseModel):
    """Response GET /api/prompts/{tool}."""
    tool: str
    default_core: str
    core_override: str | None = None
    core_is_customized: bool = False
    locked_block: str
    user_instructions: str = ""
    updated_at: str | None = None


class PromptUpdateRequest(BaseModel):
    """Payload PUT /api/prompts/{tool}."""
    core_override: str | None = None
    user_instructions: str | None = None


class PromptResetRequest(BaseModel):
    """Payload POST /api/prompts/{tool}/reset."""
    section: str = "all"   # "core" | "user" | "all"


class PromptPreviewResponse(BaseModel):
    """Response POST /api/prompts/{tool}/preview."""
    tool: str
    final_prompt: str
    total_chars: int

# ---------------------------------------------------------------------------
# Prompt Presets
# ---------------------------------------------------------------------------

class PromptPresetInfo(BaseModel):
    """Info 1 preset prompt."""
    id: str
    name: str
    description: str
    core_text: str


class PromptPresetsResponse(BaseModel):
    """Response GET /api/prompts/{tool}/presets."""
    tool: str
    presets: list[PromptPresetInfo]

# ---------------------------------------------------------------------------
# Search Global
# ---------------------------------------------------------------------------

class SearchResultItem(BaseModel):
    """1 hasil pencarian dari 1 item dalam 1 dokumen."""
    source: str                    # "regulation_audit" | "gap_analysis"
    result_id: str
    filename: str
    item_index: int
    # Field umum untuk preview
    title: str                     # ringkasan singkat (mis. point_ketentuan atau persyaratan)
    snippet: str                   # potongan teks dengan context query
    referensi: str = ""            # bab_pasal_ayat / referensi
    aspek: str = ""
    status: str = ""               # status_kepatuhan / status_gap
    created_at: str = ""           # ISO timestamp
    # Full item (untuk preview detail kalau diperlukan)
    raw_item: dict = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Response GET /api/search."""
    query: str
    total: int
    results: list[SearchResultItem]
    # Ringkasan per dokumen
    by_document: dict[str, int] = Field(default_factory=dict)
    # Filter yang diterapkan
    tools_searched: list[str] = Field(default_factory=list)
    date_filter_days: int | None = None

    # ---------------------------------------------------------------------------
# Compliance Review
# ---------------------------------------------------------------------------

class ComplianceItem(BaseModel):
    """1 baris hasil compliance review."""
    klausul_ref: str = ""
    klausul_text: str = ""
    regulasi_ref: str = ""
    # PATUH | PATUH DENGAN CATATAN | TIDAK PATUH | TIDAK RELEVAN | PERLU VERIFIKASI
    status: str = ""
    analisis: str = ""
    # Catatan validasi otomatis (kutipan regulasi tidak valid, status AI tak
    # dikenali, klausul dilewati AI, ...). needs_review=True → wajib dicek auditor.
    validation_notes: list[str] = Field(default_factory=list)
    needs_review: bool = False


class CompliancePreviewResponse(BaseModel):
    """Response preview: kontrak + regulasi sudah di-parse."""
    preview_id: str
    contract_filename: str
    regulation_filenames: list[str] = Field(default_factory=list)
    total_contract_chunks: int
    total_regulation_chunks: int
    contract_tree_preview: list[dict] = Field(default_factory=list)


class ComplianceAnalyzeRequest(BaseModel):
    """Payload POST /api/compliance/analyze."""
    preview_id: str
    nama_kontrak: str | None = None
    # Filter opsional: kalau diisi, hanya kontrak dengan keyword ini yang dianalisis
    filter_kontrak: str | None = None


class ComplianceResponse(BaseModel):
    """Response hasil compliance review."""
    result_id: str
    preview_id: str = ""
    contract_filename: str = ""
    regulation_filenames: list[str] = Field(default_factory=list)

    total_items: int
    total_patuh: int
    total_patuh_catatan: int
    total_tidak_patuh: int
    total_tidak_relevan: int
    total_perlu_verifikasi: int = 0

    items: list[ComplianceItem]
    executive_summary: str = ""

    total_contract_chunks: int = 0
    total_regulation_chunks: int = 0
    total_batches: int = 0
    filter_applied: str = ""

    # Cara regulasi diambil — dipakai ulang oleh analyze-items:
    # {"mode": "upload", "preview_id": ..., "top_k": 5}
    # {"mode": "database", "regulation_ids": [...], "top_k": 5}
    retrieval: dict = Field(default_factory=dict)
    # Peringatan untuk auditor (mis. klausul dipotong karena melebihi batas).
    warnings: list[str] = Field(default_factory=list)


class UpdateComplianceItemRequest(BaseModel):
    """Payload PATCH single item."""
    klausul_ref: str | None = None
    klausul_text: str | None = None
    regulasi_ref: str | None = None
    status: str | None = None
    analisis: str | None = None


class AddComplianceItemRequest(BaseModel):
    """Payload POST tambah baris manual."""
    klausul_ref: str = ""
    klausul_text: str = ""
    regulasi_ref: str = ""
    status: str = "TIDAK RELEVAN"
    analisis: str = ""
    insert_after: int | None = None  # None = append di akhir


class BatchAddItem(BaseModel):
    """
    Schema khusus untuk item di batch-add.
    Sederhana, tanpa insert_after per item — insert_after hanya di top-level.
    """
    klausul_ref: str = ""
    klausul_text: str = ""
    regulasi_ref: str = ""
    status: str = "TIDAK RELEVAN"
    analisis: str = ""


class BatchAddComplianceItemRequest(BaseModel):
    """Payload POST batch-add — untuk import dari PDF atau multi-clause."""
    items: list[BatchAddItem] = Field(..., min_length=1)
    insert_after: int | None = None


class ParsedContractClause(BaseModel):
    """Satu klausul hasil parse PDF kontrak."""
    pasal: str | None = None
    ayat: str | None = None
    huruf: str | None = None
    text: str = ""
    klausul_ref: str = ""  # formatted: "Pasal 6A ayat (1) huruf a)"


class ParseContractResponse(BaseModel):
    """Response POST /api/compliance/parse-contract."""
    filename: str
    total_clauses: int
    clauses: list[ParsedContractClause]


class DeleteComplianceItemsRequest(BaseModel):
    """Payload DELETE."""
    item_indices: list[int] = Field(..., min_length=1)


class BulkUpdateComplianceRequest(BaseModel):
    """Payload bulk update status."""
    item_indices: list[int] = Field(..., min_length=1)
    status: str | None = None


class ComplianceBulkResponse(BaseModel):
    affected: int
    total_items: int
    total_patuh: int
    total_patuh_catatan: int
    total_tidak_patuh: int
    total_tidak_relevan: int
    total_perlu_verifikasi: int = 0


class UpdateExecutiveSummaryRequest(BaseModel):
    """Payload PATCH untuk edit ringkasan eksekutif."""
    executive_summary: str

class AnalyzeComplianceItemsRequest(BaseModel):
    """Payload POST /api/compliance/{id}/analyze-items."""
    item_indices: list[int] = Field(..., min_length=1)

# ---------------------------------------------------------------------------
# Regulation Database (RAG)
# ---------------------------------------------------------------------------

class RegulationMeta(BaseModel):
    """Metadata 1 regulasi di database."""
    id: str
    name: str
    filename: str
    total_chunks: int
    created_at: str
    source_type: str = "manual"  # "manual" | "preload"
    file_sha256: str = ""
    parser_version: int | None = None
    index_version: int | None = None
    has_source: bool = False       # file sumber tersimpan → bisa di-index ulang
    needs_reindex: bool = False    # dibuat dengan parser/index versi lama


class ResetDBRequest(BaseModel):
    """Payload POST /api/regulation-db/reset — konfirmasi eksplisit."""
    confirm: str = ""


class ListRegulationsResponse(BaseModel):
    """Response GET /api/regulation-db/regulations."""
    regulations: list[RegulationMeta]
    total: int


class UploadRegulationResponse(BaseModel):
    """Response POST /api/regulation-db/upload."""
    regulation: RegulationMeta
    message: str = ""


class RegulationDBStatsResponse(BaseModel):
    """Response GET /api/regulation-db/stats."""
    total_regulations: int
    total_chunks: int
    db_size_mb: float


class ResetDBResponse(BaseModel):
    """Response POST /api/regulation-db/reset."""
    success: bool
    message: str = ""


class SearchDBRequest(BaseModel):
    """Payload POST /api/regulation-db/search — test retrieval."""
    query: str = Field(..., min_length=2)
    regulation_ids: list[str] | None = None
    top_k: int = Field(5, ge=1, le=20)


class SearchDBResultItem(BaseModel):
    """1 hasil pencarian di database."""
    id: str
    text: str
    regulation_name: str = ""
    referensi: str = ""
    distance: float | None = None
    page_start: int = 0
    page_end: int = 0


class SearchDBResponse(BaseModel):
    """Response POST /api/regulation-db/search."""
    query: str
    total: int
    results: list[SearchDBResultItem]

class ComplianceAnalyzeFromDbRequest(BaseModel):
    """Payload POST /api/compliance/analyze-from-db (multipart form, bukan JSON)."""
    pass  # Placeholder — schema pakai Form fields langsung di endpoint


class RetrievedRegulationInfo(BaseModel):
    """Info regulasi yang di-retrieve untuk 1 contract chunk."""
    contract_chunk_index: int
    retrieved_count: int
    regulation_names: list[str] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Regulation Chunks Viewer (Detail)
# ---------------------------------------------------------------------------

class RegulationChunkItem(BaseModel):
    """1 chunk untuk viewer detail."""
    id: str
    text: str
    referensi: str = ""
    page_start: int = 0
    page_end: int = 0
    char_count: int = 0
    word_count: int = 0
    is_anomaly: bool = False
    anomaly_reason: str = ""  # "short" | "long" | "duplicate" | ""


class RegulationChunksStats(BaseModel):
    """Statistik ringkas regulasi."""
    total_chunks: int = 0
    min_char: int = 0
    max_char: int = 0
    avg_char: float = 0.0
    total_char: int = 0
    anomaly_short: int = 0     # < 50 char
    anomaly_long: int = 0      # > 4000 char
    anomaly_duplicate: int = 0


class RegulationChunksResponse(BaseModel):
    """Response GET /api/regulation-db/regulations/{id}/chunks."""
    regulation_id: str
    regulation_name: str
    page: int = 1
    page_size: int = 20
    total: int = 0              # total setelah filter
    total_unfiltered: int = 0   # total sebelum filter
    total_pages: int = 0
    stats: RegulationChunksStats
    items: list[RegulationChunkItem] = Field(default_factory=list)
    filter_search: str = ""
    filter_anomaly: str = ""

# ---------------------------------------------------------------------------
# Background Jobs
# ---------------------------------------------------------------------------

class JobAcceptedResponse(BaseModel):
    """Response 202 dari endpoint yang menjalankan analisis di background."""
    job_id: str
    kind: str
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    """Response GET /api/jobs/{job_id}."""
    job_id: str
    kind: str
    status: str                     # queued | running | succeeded | failed | cancelled
    progress_done: int = 0
    progress_total: int = 0
    message: str = ""
    result_id: str | None = None
    result_url: str | None = None   # GET ini untuk mengambil hasil lengkap
    error: str | None = None
    partial: bool = False           # True: dibatalkan tapi hasil parsial tersimpan
    cancel_requested: bool = False
    queue_position: int = 0         # 0 = tidak sedang antre
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    extra: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tanya Regulasi (RAG Chat)
# ---------------------------------------------------------------------------

class ChatTurn(BaseModel):
    """Satu giliran percakapan sebelumnya (dikirim client untuk konteks)."""
    role: Literal["user", "assistant"]
    content: str = Field("", max_length=8000)


class ChatRequest(BaseModel):
    """Payload POST /api/chat."""
    question: str = Field(..., min_length=3, max_length=1000)
    # Kosong = cari di semua regulasi di database.
    regulation_ids: list[str] = Field(default_factory=list, max_length=50)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class ChatSource(BaseModel):
    """Kutipan regulasi yang diberikan ke AI (nomor = penanda [n] di jawaban)."""
    number: int
    regulation_id: str = ""
    regulation_name: str = ""
    reference: str = ""
    page_start: int | None = None
    text: str = ""
    cited: bool = False


class ChatResponse(BaseModel):
    """Response POST /api/chat."""
    answer: str
    found: bool = True
    cited: list[int] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    needs_review: bool = False


# =============================================================================
# BANDINGKAN REGULASI
# =============================================================================

class CompareRequest(BaseModel):
    """Payload POST /api/regulation-db/compare."""
    regulation_a: str = Field(..., min_length=1)
    regulation_b: str = Field(..., min_length=1)


class CompareChunk(BaseModel):
    """Satu ketentuan (chunk) dalam hasil perbandingan."""
    id: str
    chunk_index: int = 0
    reference: str = ""
    page_start: int | None = None
    text: str = ""


class CompareDiffSegment(BaseModel):
    """Potongan diff kata A → B."""
    op: Literal["eq", "del", "ins"]
    text: str


class CompareItem(BaseModel):
    """
    Satu baris perbandingan.
    status: identik | berubah | padanan | hanya_a | hanya_b
    """
    status: Literal["identik", "berubah", "padanan", "hanya_a", "hanya_b"]
    a: CompareChunk | None = None
    b: CompareChunk | None = None
    # hanya_a: ketentuan B terdekat (di bawah ambang padanan) sebagai petunjuk.
    nearest: CompareChunk | None = None
    similarity: float | None = None
    text_ratio: float | None = None
    diff: list[CompareDiffSegment] = Field(default_factory=list)


class CompareRegulationInfo(BaseModel):
    id: str
    name: str = ""
    total_chunks: int = 0


class CompareResponse(BaseModel):
    """Response POST /api/regulation-db/compare."""
    regulation_a: CompareRegulationInfo
    regulation_b: CompareRegulationInfo
    summary: dict[str, int]
    thresholds: dict[str, float]
    items: list[CompareItem]
