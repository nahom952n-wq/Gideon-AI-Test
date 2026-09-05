"""
Versioned prompt templates for all AI tasks.

Every prompt has a version string. When a prompt is updated, increment its
version. The version is stored alongside every AI analysis so old records
can be identified and re-processed selectively.

Never change a prompt without bumping its VERSION constant.

Phase 3 adds:
  - CLASSIFICATION_PROMPT_*  — determines opportunity type before extraction
  - OPPORTUNITY_EXTRACTION_* — generic extraction replacing the v1 scholarship-only prompt
  - PROCESSING_VERSION       — pipeline-level version stored on every Opportunity
"""

# ---------------------------------------------------------------------------
# Pipeline version (Phase 3+)
# ---------------------------------------------------------------------------
PROCESSING_VERSION = "3.0"


# ---------------------------------------------------------------------------
# Phase 1/2 — legacy scholarship extraction (preserved for re-analysis)
# ---------------------------------------------------------------------------
EXTRACTION_PROMPT_VERSION = "v1.1"

EXTRACTION_SYSTEM = """You are an opportunity data extraction expert.
Your task is to extract structured information from opportunity announcements
(scholarships, internships, fellowships, competitions, grants, jobs, research
opportunities, and similar).
Rules:
- Extract ONLY what is explicitly stated in the text.
- If a field is not mentioned, return the string "Unknown".
- Never invent or guess details.
- Return ONLY valid JSON with no markdown or code blocks.
- Dates should be in ISO 8601 format (YYYY-MM-DD) if determinable, otherwise "Unknown".
- Confidence score should be 0.0–1.0 reflecting how certain you are about the extraction.
"""

EXTRACTION_PROMPT_TEMPLATE = """Extract opportunity information from the following text.

TEXT:
{text}

Return a JSON object with exactly these fields:
{{
  "name": "...",
  "university": "...",
  "country": "...",
  "degree_level": "bachelor|master|phd|postdoc|any|Unknown",
  "funding_type": "full|partial|tuition_only|stipend_only|Unknown",
  "funding_amount": "...",
  "currency": "...",
  "deadline": "YYYY-MM-DD or Unknown",
  "deadline_raw": "...",
  "eligibility_text": "...",
  "required_docs": ["...", "..."],
  "min_gpa": null_or_float,
  "ielts_score": null_or_float,
  "toefl_score": null_or_int,
  "english_requirements": "...",
  "application_url": "...",
  "official_website": "...",
  "fields_of_study": ["...", "..."],
  "keywords": ["...", "..."],
  "summary": "...",
  "application_steps": ["...", "..."],
  "confidence": 0.0_to_1.0
}}"""


# ---------------------------------------------------------------------------
# Phase 3 — Opportunity Classification (Stage 3 of pipeline)
# ---------------------------------------------------------------------------
CLASSIFICATION_PROMPT_VERSION = "v3.0"

CLASSIFICATION_PROMPT_TEMPLATE = """Classify the following text as exactly one opportunity type.

Allowed types:
  scholarship  — academic funding for students (tuition, stipend, full ride)
  internship   — short-term work or training placement
  fellowship   — advanced research or professional development program
  grant        — funding for projects, organizations, or research
  competition  — contests, hackathons, or challenges with prizes
  research     — research assistant positions or calls for researchers
  job          — full-time or part-time employment positions
  conference   — events, symposia, workshops, or seminars
  announcement — general announcements without a clear actionable opportunity
  unknown      — cannot be determined from the text

TEXT:
{text}

Return ONLY a JSON object with no markdown:
{{"opportunity_type": "<one of the types above>", "confidence": 0.0_to_1.0}}"""


# ---------------------------------------------------------------------------
# Phase 3 — Generic Opportunity Extraction (Stage 4 of pipeline)
# ---------------------------------------------------------------------------
OPPORTUNITY_EXTRACTION_PROMPT_VERSION = "v3.0"

OPPORTUNITY_EXTRACTION_SYSTEM = """You are an opportunity data extraction expert.
Extract structured information from any opportunity announcement.
Rules:
- Extract ONLY what is explicitly stated in the text.
- Use "Unknown" for fields not present in the text.
- Return ONLY valid JSON — no markdown, no code blocks.
- Dates must be ISO 8601 (YYYY-MM-DD) or "Unknown".
- Confidence 0.0–1.0 reflects how complete and certain your extraction is.
"""

OPPORTUNITY_EXTRACTION_PROMPT_TEMPLATE = """Extract structured information from this {opportunity_type} announcement.

TEXT:
{text}

Return a JSON object with exactly these fields:
{{
  "title": "full name of the opportunity",
  "organization": "sponsoring institution, company, or agency",
  "country": "primary country (ISO name or Unknown)",
  "location": "city, region, or remote — as stated",
  "deadline": "YYYY-MM-DD or Unknown",
  "deadline_raw": "deadline text as it appears in the source",
  "start_date": "YYYY-MM-DD or Unknown",
  "summary": "2–3 sentence description of what this opportunity offers",
  "eligibility_text": "who is eligible as stated",
  "application_url": "direct application link or Unknown",
  "official_website": "official program website or Unknown",
  "keywords": ["relevant", "topic", "keywords"],
  "tags": ["tag1", "tag2"],
  "extra_fields": {{
    "comment": "put any type-specific fields here as key-value pairs",
    "examples for scholarships": "funding_amount, currency, degree_level, min_gpa",
    "examples for internships":  "duration, compensation, remote",
    "examples for grants":       "amount, eligible_organizations",
    "examples for competitions": "prize, submission_deadline, format",
    "examples for jobs":         "salary, contract_type, remote, skills_required",
    "examples for conferences":  "venue, registration_fee, paper_deadline"
  }},
  "confidence": 0.0_to_1.0
}}

Important: extra_fields should contain REAL data from the text, not the example keys above.
If no extra data is found, use an empty object: {{}}"""


# ---------------------------------------------------------------------------
# Chat (all phases)
# ---------------------------------------------------------------------------
CHAT_SYSTEM = """You are Gideon, an Opportunity Intelligence assistant.
You have access to a local opportunity database covering scholarships, internships,
fellowships, grants, competitions, research positions, jobs, and more.

When answering questions:
1. Prioritize information from the database context provided.
2. If the database has relevant information, scan and synthesize it naturally.
3. If the database context is empty or irrelevant, say so clearly before using general knowledge.
4. Never invent names, deadlines, URLs, or requirements.
5. If you use general knowledge (not from the database), prefix with: [General Knowledge]
6. Be concise, conversational, and helpful.
"""

CHAT_PROMPT_TEMPLATE = """Your current database context (list of active opportunities):
{context}

User question: {question}

Answer the user's question based on the opportunities provided in the context above.
If the context shows opportunities, scan and synthesize them naturally. 
Do not claim the database is empty if opportunities were provided."""

CHAT_PROMPT_VERSION = "v2.0"
