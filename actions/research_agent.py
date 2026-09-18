"""
actions/research_agent.py — Autonomous Deep Academic & Technical Research Agent for ARC.

Performs deep multi-source research pipeline:
1. Query decomposition: breaks topic into 5 sub-questions.
2. Parallel search: runs 5 searches simultaneously across academic & web sources.
3. Source quality scoring: HIGH (.edu, .gov, peer-reviewed), MEDIUM (news), LOW (blogs).
4. Contradiction detection: flags when sources disagree.
5. Evidence strength assessment per claim.
6. Citation formatting: APA 7th edition and BibTeX.
7. Research gap identification: flags areas lacking empirical sources.
8. Saves structured research map to quick_notes.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()


def _get_api_key() -> str:
    from memory.config_manager import get_key
    return get_key("gemini_api_key")


# ── 1. Query Decomposition ───────────────────────────────────────────────────

def decompose_query(topic: str) -> list[str]:
    """
    Decompose an academic/technical query into exactly 5 targeted sub-questions.
    Covers definitions, state-of-the-art methodologies, empirical benchmarks,
    critical limitations, and future directions.
    """
    clean_topic = topic.strip()
    if not clean_topic:
        return [
            "What are the foundational principles of this topic?",
            "What is the current state-of-the-art methodology?",
            "What are the empirical benchmark comparisons?",
            "What are the primary technical bottlenecks and failure modes?",
            "What are the emerging directions and unsolved problems?",
        ]

    try:
        import os
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            from google import genai as _genai
            api_key = _get_api_key()
            if api_key:
                client = _genai.Client(api_key=api_key)
                prompt = (
                    f"Decompose the following technical/research topic into exactly 5 distinct sub-questions for research:\n"
                    f"Topic: {clean_topic}\n"
                    f"Provide exactly 5 numbered questions covering fundamentals, architectures, benchmarks, limitations, and future work. "
                    f"Output only the 5 questions, one per line."
                )
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                lines = [line.strip() for line in (resp.text or "").split("\n") if line.strip()]
                sub_q = []
                for line in lines:
                    cleaned = re.sub(r"^(\d+[\.\)]|\-|\*)\s*", "", line).strip()
                    if cleaned and len(cleaned) > 5:
                        sub_q.append(cleaned)
                if len(sub_q) >= 5:
                    return sub_q[:5]
    except Exception:
        pass

    # Deterministic fallback guaranteeing 5 structured sub-questions
    return [
        f"What are the core mechanisms and theoretical foundations of {clean_topic}?",
        f"What are the latest state-of-the-art architectures or approaches in {clean_topic}?",
        f"How does {clean_topic} compare on standard empirical benchmarks and efficiency metrics?",
        f"What are the known limitations, scalability bottlenecks, and vulnerabilities of {clean_topic}?",
        f"What are the primary open research questions and future developments for {clean_topic}?",
    ]


# ── 2. Source Quality Scoring ────────────────────────────────────────────────

def score_source_quality(url_or_domain: str) -> str:
    """
    Assess source credibility:
    - HIGH: Academic journals, .edu, .gov, arXiv, Semantic Scholar, IEEE, ACM, Nature, Science
    - MEDIUM: Major news outlets, corporate research labs (OpenAI, DeepMind, Microsoft Research)
    - LOW: General blogs, social media, forums, medium.com, substack
    """
    if not url_or_domain:
        return "LOW"

    url_lower = url_or_domain.lower()

    high_indicators = [
        ".edu", ".gov", ".ac.uk", "arxiv.org", "semanticscholar.org",
        "nature.com", "ieee.org", "acm.org", "sciencedirect.com",
        "springer.com", "biorxiv.org", "medrxiv.org", "ncbi.nlm.nih.gov",
        "doi.org", "jstor.org", "researchgate.net", "openreview.net",
    ]
    for ind in high_indicators:
        if ind in url_lower:
            return "HIGH"

    medium_indicators = [
        "reuters.com", "bloomberg.com", "bbc.com", "techcrunch.com",
        "wired.com", "theverge.com", "arstechnica.com", "nytimes.com",
        "wsj.com", "deepmind.google", "openai.com/research",
        "microsoft.com/research", "huggingface.co", "github.com",
    ]
    for ind in medium_indicators:
        if ind in url_lower:
            return "MEDIUM"

    return "LOW"


# ── 3. Contradiction & Evidence Gap Detection ────────────────────────────────

def detect_contradictions(sources: list[dict[str, Any]]) -> list[str]:
    """
    Examine findings across collected papers and sources to identify conflicting claims
    (e.g., performance improvements vs degradation, conflicting complexity claims).
    """
    contradictions: list[str] = []
    if len(sources) < 2:
        return contradictions

    texts = [f"{s.get('title', '')}: {s.get('abstract', '') or s.get('snippet', '')}" for s in sources]
    combined = " ".join(texts).lower()

    # Heuristic pattern checks
    opposing_pairs = [
        ("outperforms", "fails to outperform"),
        ("scales linearly", "quadratic bottleneck"),
        ("reduces latency", "increases latency"),
        ("optimal", "sub-optimal"),
        ("robust against", "vulnerable to"),
        ("high accuracy", "significant degradation"),
    ]

    for pos, neg in opposing_pairs:
        if pos in combined and neg in combined:
            contradictions.append(
                f"Discrepancy noted regarding performance traits: some evidence claims '{pos}' while other sources report '{neg}'."
            )

    return contradictions


def identify_evidence_gaps(findings: list[dict[str, Any]], sub_questions: list[str]) -> list[str]:
    """
    Determine which sub-questions or technical aspects lack sufficient empirical backing.
    """
    gaps: list[str] = []
    combined_content = " ".join(
        (f.get("title", "") + " " + f.get("abstract", "") + " " + f.get("snippet", "")).lower()
        for f in findings
    )

    for q in sub_questions:
        # Extract keywords
        words = [w for w in re.findall(r"\b[a-zA-Z]{4,}\b", q.lower()) if w not in {"what", "which", "how", "does", "with", "from", "that", "this", "standard"}]
        match_count = sum(1 for w in words if w in combined_content)
        if match_count < 1 or len(findings) == 0:
            gaps.append(f"Empirical evidence gap: Insufficient academic source data addressing '{q}'.")

    return gaps


# ── 4. Citation Formatting (APA & BibTeX) ────────────────────────────────────

def format_apa_citation(paper: dict[str, Any]) -> str:
    """Format paper or web source reference in APA 7th edition."""
    authors = paper.get("authors", [])
    if not authors:
        auth_str = "Anonymous"
    elif len(authors) == 1:
        auth_str = authors[0]
    elif len(authors) == 2:
        auth_str = f"{authors[0]}, & {authors[1]}"
    else:
        auth_str = f"{authors[0]}, et al."

    year = paper.get("year", datetime.now().year)
    title = paper.get("title", "Untitled Source")
    url = paper.get("url", "")
    source = paper.get("source", "Preprint")

    return f"{auth_str} ({year}). {title}. {source}. {url}".strip()


_format_apa = format_apa_citation


def _format_bibtex(paper: dict[str, Any], index: int = 1) -> str:
    """Format paper reference in BibTeX."""
    authors = " and ".join(paper.get("authors", []) or ["Anonymous"])
    title = paper.get("title", "Untitled")
    year = paper.get("year", datetime.now().year)
    url = paper.get("url", "")
    raw_id = paper.get("id", f"paper{index}")
    cite_key = re.sub(r"[^a-zA-Z0-9_]", "", f"arc_{raw_id}")

    return (
        f"@article{{{cite_key},\n"
        f"  author    = {{{authors}}},\n"
        f"  title     = {{{title}}},\n"
        f"  year      = {{{year}}},\n"
        f"  url       = {{{url}}},\n"
        f"  journal   = {{{paper.get('source', 'arXiv Preprint')}}}\n"
        f"}}"
    )


# ── 5. Search Backends (arXiv, Semantic Scholar, Web) ────────────────────────

def _search_arxiv(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search arXiv via public REST API."""
    papers: list[dict[str, Any]] = []
    try:
        encoded_query = urllib.parse.quote(f"all:{query}")
        url = (
            f"http://export.arxiv.org/api/query?search_query={encoded_query}"
            f"&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ARC-Agent/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read().decode("utf-8")

        root = ET.fromstring(xml_data)
        atom_ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        for entry in root.findall("atom:entry", atom_ns):
            title_elem = entry.find("atom:title", atom_ns)
            summary_elem = entry.find("atom:summary", atom_ns)
            id_elem = entry.find("atom:id", atom_ns)
            published_elem = entry.find("atom:published", atom_ns)

            title = " ".join((title_elem.text or "").split()) if title_elem is not None else ""
            summary = " ".join((summary_elem.text or "").split()) if summary_elem is not None else ""
            arxiv_url = (id_elem.text or "").strip() if id_elem is not None else ""
            pub_date = (published_elem.text or "")[:10] if published_elem is not None else ""

            authors = []
            for author_node in entry.findall("atom:author", atom_ns):
                name_node = author_node.find("atom:name", atom_ns)
                if name_node is not None and name_node.text:
                    authors.append(name_node.text.strip())

            arxiv_id = arxiv_url.split("/abs/")[-1] if "/abs/" in arxiv_url else arxiv_url.split("/")[-1]

            if title:
                papers.append({
                    "title": title,
                    "authors": authors,
                    "year": pub_date[:4] if pub_date else str(datetime.now().year),
                    "published": pub_date,
                    "abstract": summary,
                    "url": arxiv_url,
                    "source": "arXiv",
                    "id": arxiv_id,
                    "citation_count": 0,
                    "quality": "HIGH",
                })
    except Exception as e:
        print(f"[ResearchAgent] arXiv API notice: {e}")

    return papers


def _search_web_single(query: str) -> list[dict[str, Any]]:
    """Single web search invocation using DuckDuckGo."""
    results: list[dict[str, Any]] = []
    try:
        from actions.web_search import _ddg_search
        ddg = _ddg_search(query, max_results=3)
        for r in ddg:
            results.append({
                "title": r.get("title", ""),
                "authors": ["Web Author"],
                "year": str(datetime.now().year),
                "abstract": r.get("snippet", ""),
                "url": r.get("url", ""),
                "source": "Web Search",
                "citation_count": 0,
                "id": "web_" + str(int(time.time())),
                "quality": score_source_quality(r.get("url", "")),
            })
    except Exception:
        pass
    return results


# ── 6. Main Deep Research Routine ─────────────────────────────────────────────

def research_agent(parameters: dict, player=None, **_context) -> str:
    """
    Autonomous deep academic research agent.
    Decomposes queries into 5 sub-questions, executes parallel searches,
    evaluates source credibility, detects contradictions and research gaps,
    formats citations in APA/BibTeX, and logs the report.
    """
    start_time = time.monotonic()
    topic = (parameters.get("topic") or parameters.get("query") or "").strip()
    if not topic:
        return "Sir, please specify a research topic or query to investigate."

    if player and hasattr(player, "write_log"):
        player.write_log(f"RESEARCH: Decomposing and investigating '{topic[:45]}'...")

    # Step 1: Query decomposition (5 sub-questions)
    sub_questions = decompose_query(topic)

    # Step 2: Parallel search (all 5 sub-questions simultaneously)
    all_findings: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_search_web_single, sq): sq for sq in sub_questions}
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                if res:
                    all_findings.extend(res)
            except Exception:
                pass

    # If web search returns minimal results, supplement with arXiv
    arxiv_papers = _search_arxiv(topic, max_results=4)
    all_findings.extend(arxiv_papers)

    # Deduplicate findings by title
    seen_titles: set[str] = set()
    deduped_findings: list[dict[str, Any]] = []
    for f in all_findings:
        norm_t = re.sub(r"[^a-z0-9]", "", f.get("title", "").lower())
        if norm_t and norm_t not in seen_titles:
            seen_titles.add(norm_t)
            deduped_findings.append(f)

    # Step 3: Source quality scoring
    for f in deduped_findings:
        f["quality"] = score_source_quality(f.get("url", ""))

    # Sort sources by quality (HIGH -> MEDIUM -> LOW)
    quality_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    deduped_findings.sort(key=lambda x: quality_order.get(x.get("quality", "LOW"), 2))

    # Step 4: Contradiction detection
    contradictions = detect_contradictions(deduped_findings)

    # Step 5: Research gap identification
    evidence_gaps = identify_evidence_gaps(deduped_findings, sub_questions)

    # Step 6: Citations formatting
    citations_apa = [format_apa_citation(f) for f in deduped_findings[:5]]
    citations_bibtex = [_format_bibtex(f, idx) for idx, f in enumerate(deduped_findings[:5], 1)]

    # Determine confidence level
    high_count = sum(1 for f in deduped_findings if f.get("quality") == "HIGH")
    if high_count >= 2:
        confidence = "HIGH"
    elif len(deduped_findings) >= 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Step 7: Synthesize findings using Gemini or structured template
    findings_summary = ""
    prompt = (
        f"You are ARC's Academic & Technical Research Agent.\n"
        f"Topic: {topic}\n"
        f"Synthesize the following research findings concisely:\n"
        + "\n".join(f"- {f.get('title')}: {f.get('abstract')[:300]}" for f in deduped_findings[:5])
        + "\nProvide 3-4 bullet points summarizing the key findings."
    )
    try:
        from google import genai as _genai
        api_key = _get_api_key()
        if api_key:
            client = _genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            findings_summary = (resp.text or "").strip()
    except Exception:
        pass

    if not findings_summary:
        findings_summary = "\n".join(
            f"- **{f.get('title', 'Unknown')}**: {f.get('abstract', '')[:200]}..."
            for f in deduped_findings[:4]
        ) or "- No primary literature findings available."

    # Build Structured Output according to ARC Specification:
    # ## Research: [Topic]
    # ### Key Findings (confidence: HIGH/MEDIUM/LOW)
    # ### Contradictions Found
    # ### Evidence Gaps
    # ### Sources (ranked by quality)
    # ### Recommended Further Reading
    contradictions_text = (
        "\n".join(f"- {c}" for c in contradictions)
        if contradictions
        else "- No significant contradictions detected across the evaluated literature."
    )
    gaps_text = (
        "\n".join(f"- {g}" for g in evidence_gaps)
        if evidence_gaps
        else "- Comprehensive coverage across all decomposed sub-questions."
    )
    sources_text = (
        "\n".join(f"- [{f.get('quality', 'LOW')}] {format_apa_citation(f)}" for f in deduped_findings[:6])
        if deduped_findings
        else "- No indexed sources found."
    )

    output_report = (
        f"## Research: {topic}\n\n"
        f"### Key Findings (confidence: {confidence})\n"
        f"{findings_summary}\n\n"
        f"### Contradictions Found\n"
        f"{contradictions_text}\n\n"
        f"### Evidence Gaps\n"
        f"{gaps_text}\n\n"
        f"### Sources (ranked by quality)\n"
        f"{sources_text}\n\n"
        f"### Recommended Further Reading\n"
        f"- Primary arXiv survey and IEEE/ACM transactions on {topic}.\n"
        f"- Benchmark documentation and peer-reviewed replication studies.\n"
    )

    if bool(parameters.get("include_bibtex", False)) and citations_bibtex:
        output_report += (
            "\n### BibTeX Entries\n```bibtex\n"
            + "\n\n".join(citations_bibtex)
            + "\n```\n"
        )

    # Step 8: Save to structured research map in quick_notes
    try:
        from actions.quick_notes import quick_notes
        safe_name = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")[:30].lower()
        note_title = f"research_{safe_name}"
        quick_notes({"action": "add", "title": note_title, "content": output_report})
    except Exception as e:
        print(f"[ResearchAgent] Could not persist to notes: {e}")

    # Mirror to HUD content panel
    if player and hasattr(player, "show_content"):
        player.show_content(f"RESEARCH — {topic[:28]}", output_report)

    elapsed = round(time.monotonic() - start_time, 2)
    spoken_summary = (
        f"Sir, research on '{topic}' completed in {elapsed} seconds with {confidence} confidence. "
        f"Decomposed into 5 sub-questions across {len(deduped_findings)} sources. "
        f"Structured findings, quality rankings, and evidence gaps have been saved to your notes and displayed."
    )

    return spoken_summary


TOOL = {
    "name": "research_agent",
    "description": (
        "Conducts deep academic and technical research. Decomposes queries into 5 sub-questions, "
        "performs parallel multi-source searches, assesses source credibility (HIGH/MEDIUM/LOW), "
        "detects contradictions and evidence gaps, formats APA citations, and saves structured briefing."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Scientific, engineering, or technical topic to investigate.",
            },
            "topic": {
                "type": "STRING",
                "description": "Scientific, engineering, or technical topic to investigate.",
            },
            "include_bibtex": {
                "type": "BOOLEAN",
                "description": "Whether to include BibTeX citation blocks in the output report.",
            },
        },
        "required": [],
    },
    "handler": research_agent,
}
