from enum import Enum

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    chunk_id: str
    source: str
    content: str
    score: float
    chunk_index: int


class ChunkRecord(BaseModel):
    chunk_id: str
    source: str
    content: str
    chunk_index: int
    metadata: dict = Field(default_factory=dict)


class IngestionResult(BaseModel):
    sources: list[str]
    chunk_count: int
    chunk_ids: list[str]


class QueryResult(BaseModel):
    answer: str
    citations: list[str]
    retrieved_chunks: list[RetrievedChunk]
    grounded: bool
    refused: bool = False


class ToolExecutionRecord(BaseModel):
    tool_name: str
    input_summary: str
    output: str
    success: bool = True


class AgentWorkflowResult(BaseModel):
    answer: str
    persona_id: str
    persona_name: str
    intent: str
    citations: list[str] = Field(default_factory=list)
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    tool_executions: list[ToolExecutionRecord] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    grounded: bool = True
    refused: bool = False


class IntentType(str, Enum):
    TECHNICAL_DOCUMENTATION = "technical_documentation"
    EDUCATION_EXPLANATION = "education_explanation"
    SOCIAL_CONTENT = "social_content"
    RESEARCH_ANALYSIS = "research_analysis"
    GENERAL_QA = "general_qa"


class PersonaDefinition(BaseModel):
    id: str
    name: str
    description: str
    supported_intents: list[str]
    style_guidelines: str
    preferred_tools: list[str]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    document_count: int
    enable_llm: bool = False
    llm_mode: str = "extractive"


class IngestPathRequest(BaseModel):
    file_path: str


class IngestResponse(IngestionResult):
    pass


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class QueryResponse(QueryResult):
    pass


class AgentQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    persona_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class AgentQueryResponse(AgentWorkflowResult):
    pass


class PersonaInfo(BaseModel):
    id: str
    name: str
    description: str
    supported_intents: list[str]


class PersonasListResponse(BaseModel):
    personas: list[PersonaInfo]
