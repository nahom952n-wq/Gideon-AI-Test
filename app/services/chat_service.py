"""
Chat service — builds DB-grounded context for the AI chat assistant.

Implements full-context retrieval model: instead of brittle keyword filtering,
retrieves a comprehensive digest of active opportunities from the database,
feeds it to the AI, and instructs the AI to act like a semantic search engine
scanning the provided entries to answer user questions naturally.

This ensures:
- No "database is empty" failures due to keyword mismatches
- Google-like conversational search experience over all collected data
- Full conversation history maintained for multi-turn memory
"""

import logging
from ..models import ChatMessage
from ..ai.gateway import AIGateway, AIRequest
from ..ai.prompts import CHAT_SYSTEM, CHAT_PROMPT_TEMPLATE

log = logging.getLogger("scholarmind.ai")

SOURCE_DATABASE = "database"
SOURCE_GENERAL = "general"

# Maximum number of opportunities to retrieve for context
MAX_CONTEXT_OPPORTUNITIES = 100

# Maximum characters for compressed context (to avoid exceeding token limits)
MAX_CONTEXT_LENGTH = 12000


class ChatService:
    """
    Handles AI chat with full-context DB grounding.
    
    Uses comprehensive retrieval instead of keyword filtering: fetches all
    active opportunities (up to 100), compresses them, and feeds to AI
    which scans them semantically like Google.
    """

    def __init__(self) -> None:
        self._gateway = AIGateway()

    def respond(self, user_message: str, session_id: int, user_id: int | None = None) -> tuple[str, str]:
        """
        Generate a response for a user message.

        Strategy:
        1. Fetch comprehensive context block (all active opportunities).
        2. Load conversation history.
        3. Build system + user prompt with context.
        4. Route to AI provider.

        Returns:
            (response_text, source) where source is "database" or "general".
        """
        context = self._build_comprehensive_context()
        source = SOURCE_DATABASE if context else SOURCE_GENERAL

        history = self._load_history(session_id, limit=6)
        history_text = "\n".join(
            f"{m.role.upper()}: {m.content}" for m in history
        )

        # Build context block: if DB has opportunities, include them all;
        # otherwise tell AI the DB is empty (use general knowledge as fallback).
        context_block = context if context else "[Database is empty]"
        prompt = CHAT_PROMPT_TEMPLATE.format(
            context=context_block, question=user_message
        )

        if history_text:
            prompt = f"Conversation history:\n{history_text}\n\n{prompt}"

        # Use custom system prompt that instructs AI to act as semantic search engine
        system_prompt = self._build_system_prompt(has_context=bool(context))
        response = self._gateway.complete(AIRequest(prompt=prompt, system=system_prompt, capability="chat", user_id=user_id))

        if not response.success:
            log.error("Chat AI call failed: %s", response.error)
            return (
                "I'm having trouble connecting to the AI service right now. "
                "Please check your API key in the .env file.",
                SOURCE_GENERAL,
            )

        return response.text.strip(), source

    def _build_system_prompt(self, has_context: bool) -> str:
        """
        Build the system prompt, with special instructions for semantic search
        when we have database context.
        """
        base_system = CHAT_SYSTEM
        
        if has_context:
            # Add powerful semantic search instruction
            semantic_search_instruction = (
                "\n\nIMPORTANT: You have been provided a comprehensive list of opportunities "
                "in your database context. Your task is to act like a powerful semantic search engine "
                "(similar to Google) that:\n"
                "1. Scans ALL entries provided in the context to understand the full landscape.\n"
                "2. Identifies entries that match the user's question conceptually, not just by keywords.\n"
                "3. Extracts and summarizes the most relevant information.\n"
                "4. Provides a natural, conversational answer that connects the data to the user's need.\n"
                "5. Never claims the database is empty if entries were provided — analyze and synthesize them."
            )
            return base_system + semantic_search_instruction
        
        return base_system

    def _build_comprehensive_context(self) -> str:
        """
        Fetch all active opportunities (up to MAX_CONTEXT_OPPORTUNITIES) from the database,
        sorted by priority, and compress them into a concise context block.
        
        Returns:
            Compressed context string ready for AI input, or empty string if no opportunities.
        """
        from ..models.opportunity import Opportunity

        # Fetch active opportunities, prioritizing by:
        # 1. Deadline urgency (upcoming deadlines first)
        # 2. Opportunity score (higher quality entries)
        # 3. Recency (newer opportunities first)
        opportunities = (
            Opportunity.query
            .filter_by(is_active=True, is_duplicate=False)
            .order_by(
                # Prioritize near deadlines (non-null, closest first)
                Opportunity.deadline.isnot(None),
                Opportunity.deadline.asc(),
                # Then by opportunity score (quality signal)
                Opportunity.opportunity_score.desc(),
                # Finally by recency
                Opportunity.created_at.desc(),
            )
            .limit(MAX_CONTEXT_OPPORTUNITIES)
            .all()
        )

        if not opportunities:
            return ""

        # Compress opportunities into concise format
        context_lines = []
        for opp in opportunities:
            compressed_line = self._format_opportunity_compact(opp)
            context_lines.append(compressed_line)

        # Join all and truncate if needed
        context_text = "\n".join(context_lines)
        if len(context_text) > MAX_CONTEXT_LENGTH:
            context_text = context_text[:MAX_CONTEXT_LENGTH] + "\n[... context truncated ...]"

        return context_text

    def _format_opportunity_compact(self, opp) -> str:
        """
        Format a single opportunity into a compact, AI-friendly string.
        
        Balances information density with conciseness.
        """
        # Extract key fields, with safe fallbacks
        title = opp.title or "Unknown"
        org = opp.organization or "Unknown"
        opp_type = opp.opportunity_type or "unknown"
        country = opp.country or "Unknown"
        deadline = opp.deadline.isoformat() if opp.deadline else "Unknown"
        
        # Extract funding/prize/salary if available
        extra = opp.extra_fields or {}
        funding_info = (
            extra.get("funding_amount") 
            or extra.get("prize") 
            or extra.get("salary")
            or extra.get("funding_type")
            or "Unknown"
        )
        
        # Compress summary to 100 chars
        summary = (opp.summary or "")[:100].strip()
        
        # Build compact line
        line = (
            f"[{opp_type.upper()}] {title} | Org: {org} | "
            f"Country: {country} | Deadline: {deadline} | "
            f"Funding: {funding_info}"
        )
        
        if summary:
            line += f" | Summary: {summary}"
        
        return line

    def _load_history(self, session_id: int, limit: int = 6) -> list:
        """Load conversation history for context."""
        return (
            ChatMessage.query.filter_by(session_id=session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()[::-1]
        )
