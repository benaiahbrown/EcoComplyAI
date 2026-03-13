# backend/simple_agent.py
import httpx
import os
import json
import asyncio
import re
from typing import List, Dict, Optional
from dotenv import load_dotenv
from openai import OpenAI
from landrag import query_rag, vectorstore

load_dotenv()

# Initialize OpenRouter client
openrouter_client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

# Initialize Gemini client for web search
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")

def strip_markdown(text: str) -> str:
    """Strip markdown formatting from text to prevent formatting corruption in conversation history"""
    if not text:
        return text
    
    # Remove bold/italic markers (**text**, *text*, __text__, _text_)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *italic* (but not **)
    text = re.sub(r'__([^_]+)__', r'\1', text)       # __bold__
    text = re.sub(r'_([^_]+)_', r'\1', text)        # _italic_ (but not __)
    
    # Remove headers (# ## ###)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # Remove links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # Remove inline code `code`
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # Remove code blocks ```code```
    text = re.sub(r'```[\s\S]*?```', '', text)
    
    # Clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newlines
    text = text.strip()
    
    return text

SYSTEM_MESSAGE = """You are a research assistant focused on compliance and regulation, specifically for landowners trying to maintain environmental compliance.

Your primary responsibilities:

1. Always use uptodate, external sources
- Before answering, you must check current, authoritative sources (e.g., official federal and state government websites, current regulations, and recent court decisions).
- Do not rely solely on static or past knowledge if newer information may exist.
- When rules have changed (e.g., proposals finalized, standards rescinded, deadlines extended, or litigation affecting enforceability), your answer must reflect the *current* status, not just the original rule text.

2. Distinguish clearly between legal states
For every regulatory description, explicitly and clearly indicate:
- Whether a standard is a final, legally enforceable requirement, a proposed rule, a guidance/advisory, or a standard that an agency has announced an intent to rescind.
- Whether any relevant portions are stayed, vacated, remanded, or otherwise limited by a court.
- If litigation or rulemaking is pending, explain what is in effect *today* and what changes are being contemplated.

3. Prioritize precision over speculation
- Do not guess or project future regulatory outcomes.
- If the current status is uncertain, say so explicitly.
- Never fabricate details about regulations, dates, or legal interpretations.

4. Handle time sensitivity explicitly
- Assume the user cares about the regulatory situation as of the moment you answer.
- When discussing timelines, provide specific dates and note if those dates have been revised.

5. Source transparency
- Cite sources clearly.
- When summarizing complex changes, briefly explain: what the original rule did, what has changed, and what is currently enforceable.

6. Userfocused, cautious guidance
- Use clear, plain language suitable for nonlawyers while preserving legal accuracy.
"""

# ===== AGENT 1: RAG SEARCH ONLY =====
async def search_rag_only(query: str, conversation_history: List[Dict] = None) -> dict:
    """
    Agent 1: Search internal RAG database
    Uses the full RAG chain from landrag.py
    Returns answer with source document filenames
    
    Args:
        query: The current question to search
        conversation_history: Optional list of previous Q&A pairs for context
    """
    print(f"🔍 Agent 1: Searching RAG database...")
    if conversation_history:
        print(f"   💬 Using conversation context ({len(conversation_history)} previous exchanges)")

    try:
        # Use the query_rag function from landrag.py with conversation history
        result = await query_rag(query, conversation_history=conversation_history)

        # Extract answer and sources
        answer = result.get('answer', '')
        rag_source_list = result.get('sources', [])
        
        # If no sources from metadata, try to extract from answer text as fallback
        if not rag_source_list:
            # Look for common document extensions in the answer
            import re
            # Pattern to find filenames with extensions
            filename_pattern = r'\b[\w\-_]+\.(pdf|txt|docx|doc)\b'
            found_files = re.findall(filename_pattern, answer, re.IGNORECASE)
            if found_files:
                # Try to find full filename context
                for match in re.finditer(r'[\w\-_/]+\.(pdf|txt|docx|doc)', answer, re.IGNORECASE):
                    filename = match.group(0)
                    if filename not in rag_source_list:
                        rag_source_list.append(filename)

        print(f"✅ Agent 1 complete: Found {len(rag_source_list)} source documents")
        if rag_source_list:
            print(f"   Sources: {', '.join(rag_source_list[:3])}{'...' if len(rag_source_list) > 3 else ''}")

        return {
            'answer': answer,
            'sources': rag_source_list,
            'confidence': 'high' if len(answer) > 100 and len(rag_source_list) > 0 else 'low'
        }

    except Exception as e:
        print(f"❌ Agent 1 error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'answer': f"RAG search error: {str(e)}",
            'sources': [],
            'confidence': 'none'
        }

# ===== AGENT 2: WEB SEARCH ONLY =====
async def search_web_only(query: str, conversation_history: List[Dict] = None) -> dict:
    """Agent 2: Search web using Gemini 2.5 Flash with Google grounding
    
    Args:
        query: The current question to search
        conversation_history: Optional list of previous Q&A pairs for context
    """
    print(f"🌐 Agent 2: Searching web with grounding...")
    if conversation_history:
        print(f"   💬 Using conversation context ({len(conversation_history)} previous exchanges)")

    # Build conversation context string
    conversation_context = ""
    if conversation_history:
        conv_lines = []
        for entry in conversation_history:
            user_q = entry.get('user_query', '')
            assistant_a = entry.get('final_answer', '')
            if user_q:
                conv_lines.append(f"User: {user_q}")
            if assistant_a:
                # Strip markdown to prevent formatting corruption, then truncate
                clean_answer = strip_markdown(assistant_a)
                truncated_answer = clean_answer[:300] + "..." if len(clean_answer) > 300 else clean_answer
                conv_lines.append(f"Assistant: {truncated_answer}")
        
        if conv_lines:
            conversation_context = "\n\nPrevious conversation:\n" + "\n".join(conv_lines) + "\n"

    prompt = f"""{conversation_context}Search for current, authoritative information about: {query}

Focus on:
- Official government sources (EPA, state agencies)
- Recent regulatory updates and rule changes
- Current enforcement status and legal challenges
- Specific dates, deadlines, and compliance requirements

Provide a comprehensive answer with inline citations. If the question refers to something from the previous conversation, use that context to provide a specific answer."""

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": SYSTEM_MESSAGE}]},
        "tools": [{"googleSearch": {}}]
    }

    try:
        # Increase timeout for web search with grounding (can take longer)
        # Use a more generous timeout: 120 seconds for read, 30 seconds for connect
        timeout = httpx.Timeout(120.0, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        candidates = data.get('candidates', [])
        if not candidates:
            return {'answer': "No web results found", 'web_sources': []}

        # Extract answer
        parts = candidates[0].get('content', {}).get('parts', [])
        answer = ''.join([part.get('text', '') for part in parts if 'text' in part])

        # Extract web sources from grounding metadata
        grounding_metadata = candidates[0].get('groundingMetadata', {})
        web_sources = []

        for chunk in grounding_metadata.get('groundingChunks', []):
            if 'web' in chunk:
                web_sources.append({
                    'url': chunk['web'].get('uri', ''),
                    'title': chunk['web'].get('title', 'Unknown')
                })

        print(f"✅ Agent 2 complete: {len(web_sources)} web sources found")

        return {
            'answer': answer,
            'web_sources': web_sources
        }

    except httpx.ReadTimeout:
        print(f"❌ Agent 2 error: Request timed out (Gemini API took too long)")
        return {
            'answer': "I'm having trouble accessing current web information right now. Please try again in a moment.",
            'web_sources': []
        }
    except httpx.ConnectTimeout:
        print(f"❌ Agent 2 error: Connection timeout (could not reach Gemini API)")
        return {
            'answer': "Unable to connect to search services. Please check your internet connection and try again.",
            'web_sources': []
        }
    except httpx.HTTPStatusError as e:
        print(f"❌ Agent 2 HTTP error: {e.response.status_code} - {e.response.text}")
        return {
            'answer': f"Search service returned an error. Please try again later.",
            'web_sources': []
        }
    except Exception as e:
        print(f"❌ Agent 2 error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'answer': f"Web search temporarily unavailable. Please try again.",
            'web_sources': []
        }

# ===== AGENT 3: GAP IDENTIFIER + SEVERITY CLASSIFICATION =====
async def identify_gaps(query: str, rag_result: dict, web_result: dict) -> dict:
    """
    Agent 3: Identify what's MISSING or INACCURATE in RAG compared to web
    Returns structured gap analysis with severity classification (GREEN/YELLOW/RED)
    """
    print(f"🔍 Agent 3: Analyzing RAG gaps and classifying severity...")
    
    # Check RAG content status for logging
    rag_answer_length = len(rag_result.get('answer', '').strip())
    rag_source_count = len(rag_result.get('sources', []))
    print(f"   RAG status: answer_length={rag_answer_length}, sources={rag_source_count}")

    prompt = f"""Compare these two answers and identify what relevant information is MISSING or INACCURATE in the RAG answer.

USER QUESTION:
{query}

RAG ANSWER (Internal Database):
{rag_result['answer']}

RAG Sources: {', '.join(rag_result['sources']) if rag_result['sources'] else 'No sources found'}
RAG Confidence: {rag_result.get('confidence', 'unknown')}

WEB ANSWER (Current Information):
{web_result['answer']}

Web Sources Available: {len(web_result['web_sources'])} sources

YOUR TASK:
1. Identify what relevant information is MISSING or INACCURATE in the RAG answer
2. Classify the severity of gaps using these criteria:

SEVERITY CLASSIFICATION:
- RED: Missing foundational regulations, major legal challenges, decision-changing gaps, litigation impacts, or jurisdiction differences that could lead to non-compliance
- YELLOW: Supplementary context, minor updates, clarifications, or non-critical information that enhances understanding but doesn't change core compliance requirements
- GREEN: No substantive gaps - RAG answer is current, complete, and accurate

IMPORTANT:
- If RAG answer is complete and accurate, write "None - RAG is current and complete" and assign GREEN
- If RAG has gaps, list each gap as a specific bullet point
- Focus on substantive gaps (not minor wording differences)
- Consider the impact: Would missing this information cause compliance issues or legal problems?

OUTPUT FORMAT (you MUST include both sections):
===GAPS===
[Either "None - RAG is current and complete" OR list of specific gaps as bullet points]

===SEVERITY===
[Exactly one word: GREEN, YELLOW, or RED]
[Brief explanation of why this severity was chosen]
"""

    try:
        response = openrouter_client.chat.completions.create(
            model="x-ai/grok-4-fast",
            messages=[
                {"role": "system", "content": "You are an objective analyst identifying knowledge gaps and classifying their severity. Be precise and concise. Always output both GAPS and SEVERITY sections."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        analysis_text = response.choices[0].message.content

        # Parse gaps
        gaps = []
        is_complete = False
        alert_level = 'GREEN'  # Default

        # Extract gaps section
        if "===GAPS===" in analysis_text:
            gaps_section = analysis_text.split("===GAPS===")[1]
            if "===SEVERITY===" in gaps_section:
                gaps_text = gaps_section.split("===SEVERITY===")[0].strip()
            else:
                gaps_text = gaps_section.strip()
        else:
            gaps_text = analysis_text

        # Check for "None" or "complete" indicators (but only if it's the main message)
        if "None" in gaps_text and ("complete" in gaps_text.lower() or "RAG is current" in gaps_text):
            is_complete = True
        else:
            # Extract bullet points - be more flexible with patterns
            for line in gaps_text.split('\n'):
                line = line.strip()
                # Match various bullet point formats
                if line and (line.startswith('-') or line.startswith('•') or line.startswith('*') or 
                            line[0].isdigit() and ('.' in line[:3] or ')' in line[:3])):
                    # Remove bullet markers more carefully
                    gap = line.lstrip('-•*0123456789. )').strip()
                    if gap and len(gap) > 10:
                        gaps.append(gap)

        # Check if RAG actually provided useful content (not just "I can't answer")
        rag_answer = rag_result.get('answer', '').strip().lower()
        rag_has_useful_content = (
            len(rag_result.get('answer', '').strip()) > 50 and  # Substantial answer
            len(rag_result.get('sources', [])) > 0 and  # Has sources
            not any(phrase in rag_answer for phrase in ['cannot answer', 'does not contain', 'no information', 'not included', 'unable to'])
        )
        
        # Extract severity/alert_level FIRST (before overrides)
        if "===SEVERITY===" in analysis_text:
            severity_section = analysis_text.split("===SEVERITY===")[1].strip()
            # Look for GREEN, YELLOW, or RED in the severity section (check first few lines)
            severity_lines = severity_section.split('\n')[:3]  # Check first 3 lines
            severity_upper = ' '.join(severity_lines).upper()
            if 'RED' in severity_upper:
                alert_level = 'RED'
            elif 'YELLOW' in severity_upper:
                alert_level = 'YELLOW'
            elif 'GREEN' in severity_upper:
                alert_level = 'GREEN'
        else:
            # Fallback: infer from gaps and RAG content
            if not rag_has_useful_content:
                # RAG provided nothing useful - this is a RED alert
                alert_level = 'RED'
                if len(gaps) == 0:
                    gaps.append("RAG database has no information on this topic")
            elif is_complete or len(gaps) == 0:
                # RAG has content and no gaps identified
                alert_level = 'GREEN'
            elif len(gaps) >= 3 or any(keyword in ' '.join(gaps).lower() for keyword in ['regulation', 'legal', 'litigation', 'enforcement', 'compliance', 'violation', 'missing', 'outdated', 'fails', 'omits', 'lacks']):
                alert_level = 'RED'
            else:
                alert_level = 'YELLOW'

        # Final overrides: Respect extracted severity if gaps were found
        if not rag_has_useful_content:
            alert_level = 'RED'
            if len(gaps) == 0:
                gaps.append("RAG database has no information on this topic")
            print(f"   ⚠️  RAG has no useful content - forcing RED alert")
        elif len(gaps) > 0:
            # If gaps were found, respect the severity from LLM (don't override to GREEN)
            # Only override if severity wasn't extracted and we need to infer
            if alert_level == 'GREEN' and len(gaps) > 0:
                # Gaps found but severity is GREEN - this is inconsistent, upgrade to at least YELLOW
                alert_level = 'YELLOW' if len(gaps) < 3 else 'RED'
                print(f"   ⚠️  Gaps found but severity was GREEN - correcting to {alert_level}")
        elif is_complete and rag_has_useful_content:
            # Only set GREEN if RAG actually has content AND no gaps
            alert_level = 'GREEN'
            print(f"   ✅ RAG has content and no gaps - GREEN alert")

        print(f"✅ Agent 3 complete: {len(gaps)} gaps identified, severity: {alert_level}")
        if gaps:
            print(f"   Gaps: {gaps[:2]}{'...' if len(gaps) > 2 else ''}")
        else:
            print(f"   ⚠️  No gaps extracted from raw response (may indicate parsing issue)")
            if "===GAPS===" in analysis_text:
                print(f"   Debug: GAPS section found but not parsed. First 200 chars: {analysis_text.split('===GAPS===')[1][:200]}")

        return {
            'gaps': gaps,
            'has_gaps': len(gaps) > 0 and not is_complete,
            'alert_level': alert_level,
            'raw_response': analysis_text
        }

    except Exception as e:
        print(f"❌ Agent 3 error: {e}")
        has_gaps = len(rag_result['sources']) < 2 and len(web_result['web_sources']) > 0
        # Default to YELLOW on error if there are gaps, GREEN if no gaps
        default_alert = 'YELLOW' if has_gaps else 'GREEN'
        return {
            'gaps': ['Gap analysis failed - defaulting to web'] if has_gaps else [],
            'has_gaps': has_gaps,
            'alert_level': default_alert,
            'raw_response': f"Error: {str(e)}"
        }

# ===== AGENT 4: URL SELECTOR (CONDITIONAL, SEVERITY-CAPPED) =====
async def select_update_urls(gaps: list, web_sources: list, query: str, alert_level: str = 'YELLOW') -> dict:
    """
    Agent 4: Select URLs to fill gaps, capped by severity
    ONLY runs if alert_level != GREEN
    
    Severity caps per PRD:
    - RED: Up to 8 URLs
    - YELLOW: Up to 4 URLs
    - GREEN: 0 URLs (should not call this function)
    """
    if not gaps or alert_level == 'GREEN':
        print(f"⏭️  Agent 4: Skipped (no gaps or GREEN severity)")
        return {'recommended_urls': []}

    # Determine URL cap based on severity
    url_cap = 8 if alert_level == 'RED' else 4 if alert_level == 'YELLOW' else 0
    if url_cap == 0:
        print(f"⏭️  Agent 4: Skipped (GREEN severity)")
        return {'recommended_urls': []}

    print(f"🔗 Agent 4: Selecting up to {url_cap} URLs (severity: {alert_level}) to fill {len(gaps)} gaps...")

    # Format web sources for display (show actual URLs, not redirect links)
    # Show more sources than cap to give LLM options
    max_sources_to_show = min(20, len(web_sources))
    formatted_sources = []
    for i, source in enumerate(web_sources[:max_sources_to_show]):
        # Extract actual URL (not grounding redirect)
        actual_url = source.get('url', '')
        title = source.get('title', 'Unknown')
        formatted_sources.append(f"{i+1}. {actual_url} | {title}")

    prompt = f"""Select the most relevant URLs to fill these knowledge gaps.

USER QUESTION:
{query}

SEVERITY: {alert_level}
- RED: Missing foundational regulations or major legal challenges
- YELLOW: Supplementary context or minor updates

IDENTIFIED GAPS IN RAG DATABASE:
{chr(10).join(f'- {gap}' for gap in gaps)}

AVAILABLE WEB SOURCES (from search):
{chr(10).join(formatted_sources)}

YOUR TASK:
Select up to {url_cap} URLs by their numbers (1-{len(formatted_sources)}) that would best fill the identified gaps.

SELECTION CRITERIA:
- Prioritize official government sources (.gov)
- Choose comprehensive resources over fragmented ones
- Prefer primary sources (regulations, statutes) over news articles
- Select URLs that address multiple gaps if possible
- For RED severity: Focus on foundational regulations and critical compliance information
- For YELLOW severity: Focus on supplementary context and clarifications

OUTPUT FORMAT (just list the numbers, up to {url_cap}):
1
2
3
...

Then explain your reasoning briefly.
"""

    try:
        response = openrouter_client.chat.completions.create(
            model="x-ai/grok-4-fast",
            messages=[
                {"role": "system", "content": f"You are a research librarian selecting the most authoritative sources to fill knowledge gaps. Select up to {url_cap} URLs based on severity {alert_level}."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        selection_text = response.choices[0].message.content

        # Parse selected indices
        import re
        selected_indices = []
        for line in selection_text.split('\n'):
            # Look for numbers at start of line
            match = re.match(r'^(\d+)', line.strip())
            if match:
                idx = int(match.group(1)) - 1  # Convert to 0-indexed
                if 0 <= idx < len(web_sources):
                    selected_indices.append(idx)

        # Build URL list with reasons, enforcing cap
        selected_urls = []
        for idx in selected_indices[:url_cap]:  # Enforce severity-based cap
            if idx < len(web_sources):
                source = web_sources[idx]
                selected_urls.append({
                    'url': source.get('url', ''),
                    'title': source.get('title', 'Unknown'),
                    'reason': f"Fills gap - {source.get('title', 'source')[:50]}"
                })

        # If parsing failed, just take top URLs up to cap
        if len(selected_urls) == 0:
            selected_urls = [
                {
                    'url': s.get('url', ''),
                    'title': s.get('title', 'Unknown'),
                    'reason': 'Top search result'
                }
                for s in web_sources[:url_cap]
            ]

        # Final enforcement: never exceed cap
        selected_urls = selected_urls[:url_cap]

        print(f"✅ Agent 4 complete: {len(selected_urls)} URLs selected (cap: {url_cap}, severity: {alert_level})")

        return {'recommended_urls': selected_urls}

    except Exception as e:
        print(f"❌ Agent 4 error: {e}")
        # Fallback: recommend top URLs up to cap
        return {
            'recommended_urls': [
                {
                    'url': s.get('url', ''),
                    'title': s.get('title', 'Unknown'),
                    'reason': 'Top search result'
                }
                for s in web_sources[:url_cap]
            ]
        }

# ===== AGENT 6: CONSOLIDATION & GAP ANALYSIS =====
async def consolidate_results(query: str, rag_result: dict, web_result: dict) -> dict:
    """
    Agent 3: Consolidate answers using Grok 4 Fast
    Explicitly compare RAG vs web and identify gaps
    """
    print(f"🔗 Agent 3: Consolidating and analyzing gaps...")

    # FIXED: Added curly braces for all variables
    consolidation_prompt = f"""You are comparing two answers to synthesize the best response and identify knowledge gaps.

USER QUESTION:
{query}

RAG DATABASE ANSWER (from internal documents):
{rag_result['answer']}

RAG Sources Used: {', '.join(rag_result['sources']) if rag_result['sources'] else 'No internal sources found'}
RAG Confidence: {rag_result.get('confidence', 'unknown')}

WEB SEARCH ANSWER (from current web sources):
{web_result['answer']}

Web Sources Available: {len(web_result['web_sources'])} sources

YOUR DECISION LOGIC:
1. **If RAG found good sources that fully answer the question:**
   - Use the RAG answer as your primary response
   - DO NOT flag for RAG update
   - DO NOT recommend URLs unless web reveals the RAG info is outdated/incomplete

2. **If RAG has no sources OR incomplete answer:**
   - Combine RAG + web information
   - Flag: "⚠️ RAG UPDATE NEEDED"
   - Recommend URLs to fill gaps

3. **If RAG answer conflicts with newer web information:**
   - Explain what changed and when
   - Use web answer for current status
   - Recommend URLs with updated regulations

YOUR TASKS:
1. Write a comprehensive answer (prefer RAG when it's complete and current)
2. Identify ONLY critical gaps (not minor updates)
3. Recommend URLs ONLY if RAG truly lacks important information

YOU MUST USE THIS EXACT FORMAT:

===FINAL_ANSWER===
[Your synthesized response. If RAG fully answered it, keep it concise. Only add "⚠️ RAG UPDATE NEEDED" if RAG actually has gaps]

===RAG_GAPS===
[ONLY list gaps if RAG was incomplete or outdated. If RAG answered well, write "None - RAG database contains sufficient information"]

===RECOMMENDED_URLS===
{chr(10).join([f"- {s['url']} | {s['title']}" for s in web_result['web_sources'][:10]])}
[From the list above, select ONLY URLs that fill critical gaps. If RAG was complete, write "None needed"]
"""

    try:
        response = openrouter_client.chat.completions.create(
            model="x-ai/grok-4-fast",
            messages=[
                {"role": "system", "content": "You are an expert at synthesizing information and identifying knowledge gaps. Always use the exact format requested."},
                {"role": "user", "content": consolidation_prompt}
            ],
            temperature=0.2
        )

        consolidated = response.choices[0].message.content

        # Parse structured sections
        final_answer = ""
        rag_gaps = []
        recommended_urls = []

        # Split by section markers
        if "===FINAL_ANSWER===" in consolidated:
            answer_section = consolidated.split("===FINAL_ANSWER===")[1]
            if "===RAG_GAPS===" in answer_section:
                final_answer = answer_section.split("===RAG_GAPS===")[0].strip()
            else:
                final_answer = answer_section.strip()

        if "===RAG_GAPS===" in consolidated:
            gaps_section = consolidated.split("===RAG_GAPS===")[1]
            if "===RECOMMENDED_URLS===" in gaps_section:
                gaps_text = gaps_section.split("===RECOMMENDED_URLS===")[0].strip()
            else:
                gaps_text = gaps_section.strip()

            # Extract bullet points
            for line in gaps_text.split('\n'):
                line = line.strip()
                if line.startswith('-') or line.startswith('•'):
                    gap = line.lstrip('-•').strip()
                    if gap and len(gap) > 5:  # Filter out empty or very short entries
                        rag_gaps.append(gap)

        if "===RECOMMENDED_URLS===" in consolidated:
            urls_section = consolidated.split("===RECOMMENDED_URLS===")[1].strip()

            # Extract URLs from recommendations
            for line in urls_section.split('\n'):
                if 'URL:' in line or 'http' in line:
                    # Extract URL from line
                    for source in web_result['web_sources']:
                        if source['url'] in line:
                            if source['url'] not in recommended_urls:
                                recommended_urls.append(source['url'])
                                break

        # Fallback: If no RAG sources and web sources exist, recommend all web sources
        if len(rag_result['sources']) == 0 and len(web_result['web_sources']) > 0:
            if len(rag_gaps) == 0:
                rag_gaps = ["RAG database has no information on this topic"]
            if len(recommended_urls) == 0:
                # Recommend top 5 web sources
                recommended_urls = [s['url'] for s in web_result['web_sources'][:5]]

        print(f"✅ Agent 3 complete: {len(rag_gaps)} gaps identified, {len(recommended_urls)} URLs recommended")

        # Add consistent alert if RAG needs update
        if len(recommended_urls) > 0 and "⚠️ RAG UPDATE NEEDED" not in final_answer:
            final_answer = "⚠️ **RAG UPDATE NEEDED** - The internal database lacks current information on this topic.\n\n" + final_answer

        return {
            'answer': final_answer,
            'rag_only_answer': rag_result['answer'],  # Agent 1 output
            'web_only_answer': web_result['answer'],  # Agent 2 output
            'rag_sources': rag_result['sources'],
            'web_sources': web_result['web_sources'],
            'rag_gaps': rag_gaps,
            'rag_update_urls': recommended_urls
        }

    except Exception as e:
        print(f"❌ Agent 3 error: {e}")
        # Fallback
        return {
            'answer': web_result['answer'],
            'rag_only_answer': rag_result['answer'],
            'web_only_answer': web_result['answer'],
            'rag_sources': rag_result['sources'],
            'web_sources': web_result['web_sources'],
            'rag_gaps': ['Consolidation failed'],
            'rag_update_urls': [s['url'] for s in web_result['web_sources'][:3]],
            'error': str(e)
        }

# ===== MAIN ORCHESTRATOR (5-AGENT PIPELINE) =====
async def run_compliance_query(query: str, conversation_history: List[Dict] = None):
    """
    Orchestrates 5-agent pipeline

    Flow:
    1. Agents 1 & 2 run in PARALLEL (RAG + Web)
    2. Agent 3 runs (Gap analysis)
    3. Agent 4 runs CONDITIONALLY (URL selection if gaps exist)
    4. Agent 5 runs (Router/formatter)
    
    Args:
        query: The current question
        conversation_history: Optional list of previous Q&A pairs for context
    """
    print(f"{'='*60}")
    print(f"🚀 Starting 5-agent pipeline")
    print(f"{'='*60}")

    # PARALLEL: Agents 1 & 2
    print(f"\n[Phase 1] Running Agents 1 & 2 in parallel...")
    rag_task = search_rag_only(query, conversation_history=conversation_history)
    web_task = search_web_only(query, conversation_history=conversation_history)

    rag_result, web_result = await asyncio.gather(rag_task, web_task)

    # SEQUENTIAL: Agent 3
    print(f"\n[Phase 2] Running Agent 3...")
    gap_result = await identify_gaps(query, rag_result, web_result)

    # CONDITIONAL: Agent 4 (per PRD: Agent 5 removed, no routing/synthesis)
    alert_level = gap_result.get('alert_level', 'GREEN')
    print(f"\n[Phase 3] Running Agent 4 (conditional, alert_level: {alert_level})...")
    if alert_level != 'GREEN':
        url_result = await select_update_urls(
            gap_result['gaps'],
            web_result['web_sources'],
            query,
            alert_level  # Pass alert_level for URL capping
        )
    else:
        url_result = {'recommended_urls': []}

    # Per PRD v2.0: Agent 5 removed - no routing, no "best-answer" selection, no synthesis
    # Return structured result for admin analysis
    final_result = {
        'rag_only_answer': rag_result['answer'],
        'rag_sources': rag_result['sources'],
        'web_only_answer': web_result['answer'],
        'web_sources': web_result['web_sources'],
        'gaps_identified': gap_result['gaps'],
        'alert_level': alert_level,
        'recommended_urls': url_result.get('recommended_urls', []),
        'status': 'COMPLETE'
    }

    print(f"\n{'='*60}")
    print(f"✅ Admin analysis pipeline complete")
    print(f"   Alert Level: {alert_level}")
    print(f"   RAG Sources: {len(final_result['rag_sources'])}")
    print(f"   Web Sources: {len(final_result['web_sources'])}")
    print(f"   Gaps: {len(final_result['gaps_identified'])}")
    print(f"   Recommended URLs: {len(final_result['recommended_urls'])}")
    print(f"{'='*60}")

    return final_result


# ===== BACKGROUND ADMIN ANALYSIS =====
async def run_admin_analysis(query_id: str, query: str, web_result: dict, initial_log: dict, conversation_history: List[Dict] = None):
    """
    Background task: Run full 5-agent analysis for admin dashboard
    Updates Supabase with complete analysis results
    
    Args:
        query_id: Unique identifier for this query
        query: The current question
        web_result: Results from Agent 2 (web search)
        initial_log: Initial log data to insert
        conversation_history: Optional list of previous Q&A pairs for context
    """
    from supabase import create_client
    from dotenv import load_dotenv

    load_dotenv()

    print(f"\n{'='*60}")
    print(f"🔄 Starting background admin analysis for query_id={query_id}")
    print(f"{'='*60}")

    try:
        # Initialize Supabase client
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )

        # Insert initial log
        supabase.table('compliance_queries').insert(initial_log).execute()
        print(f"✅ Logged initial response: query_id = {query_id}")

        # CHANGED: Async URL resolution
        from main import resolve_web_sources  # Make sure it's the async version
        if 'web_sources' in web_result and web_result['web_sources']:
            print(f"🔗 Resolving {len(web_result['web_sources'])} web source URLs...")
            web_result['web_sources'] = await resolve_web_sources(web_result['web_sources'])

        # Run Agent 1 (RAG search) with conversation history
        print(f"\n[Agent 1] Running RAG search...")
        rag_result = await search_rag_only(query, conversation_history=conversation_history)

        # Run Agent 3 (Gap analysis)
        print(f"\n[Agent 3] Running gap analysis...")
        gap_result = await identify_gaps(query, rag_result, web_result)

        # Run Agent 4 (URL selection) - conditional based on alert_level
        alert_level = gap_result.get('alert_level', 'GREEN')
        print(f"\n[Agent 4] Running URL selection (alert_level: {alert_level})...")
        if alert_level != 'GREEN':
            url_result = await select_update_urls(
                gap_result['gaps'],
                web_result['web_sources'],
                query,
                alert_level  # Pass alert_level for URL capping
            )
        else:
            url_result = {'recommended_urls': []}

        # Map alert_level to queue priority per PRD: RED=high, YELLOW=medium, GREEN=not queued
        priority_map = {
            'RED': 'high',
            'YELLOW': 'medium',
            'GREEN': None  # Not queued
        }
        queue_priority = priority_map.get(alert_level, 'medium')

        # Update Supabase record with admin analysis
        print(f"\n[Supabase] Updating record {query_id} with admin analysis...")

        update_data = {
            'rag_only_answer': rag_result['answer'],
            'rag_sources': rag_result['sources'],
            'agent1_confidence': rag_result.get('confidence', 'unknown'),

            'rag_gaps_identified': gap_result['gaps'],
            'agent3_has_gaps': gap_result['has_gaps'],
            'agent3_raw_response': gap_result.get('raw_response', ''),
            'alert_level': alert_level,  # Add severity classification

            'agent4_recommended_urls': url_result.get('recommended_urls', []),
            'agent4_ran': len(url_result.get('recommended_urls', [])) > 0,
            'rag_update_urls': [
                url.get('url', '') if isinstance(url, dict) else url
                for url in url_result.get('recommended_urls', [])
            ],

            'rag_update_flag': gap_result['has_gaps']
        }

        supabase.table('compliance_queries').update(update_data).eq('id', query_id).execute()

        # Add URLs to update queue if needed (only RED/YELLOW, not GREEN)
        if update_data['agent4_ran'] and alert_level != 'GREEN':
            for url_obj in url_result['recommended_urls']:
                if isinstance(url_obj, dict):
                    queue_data = {
                        'source_url': url_obj.get('url', ''),
                        'source_title': url_obj.get('title', url_obj.get('reason', 'Recommended by Agent 4')),
                        'related_query_id': query_id,
                        'priority': queue_priority,  # Map from severity: RED=high, YELLOW=medium
                        'processed': False
                    }
                    supabase.table('rag_update_queue').insert(queue_data).execute()
            print(f"✅ Added {len(url_result['recommended_urls'])} URLs to update queue with priority={queue_priority}")

        print(f"\n{'='*60}")
        print(f"✅ Background admin analysis complete for query_id={query_id}")
        print(f"   RAG Sources: {len(rag_result['sources'])}")
        print(f"   Gaps: {len(gap_result['gaps'])}")
        print(f"   Recommended URLs: {len(url_result.get('recommended_urls', []))}")
        print(f"{'='*60}")

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ Background analysis failed for query_id={query_id}")
        print(f"   Error: {str(e)}")
        print(f"{'='*60}")
        import traceback
        traceback.print_exc()
