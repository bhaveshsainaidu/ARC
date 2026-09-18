"""
actions/reproducibility_agent.py — ARC Scientific Paper & ML Model Reproducibility Audit Agent.

Audits scientific research papers, ML model cards, and experiment repositories for empirical reproducibility:
- Hyperparameter disclosure (learning rate, optimizer, batch size, epochs, decay)
- Random seed specifications & statistical variance reporting (trials, p-values, standard deviations)
- Compute hardware & infrastructure transparency (GPU models, VRAM, node count, CUDA versions)
- Software dependency pinning (requirements.txt, environment.yml, Docker)
- Code & dataset accessibility (public repository links, HuggingFace/Zenodo DOIs, split ratios)
- Evaluation metric rigor (confidence intervals, baseline comparisons)
- Computes composite 0-100% Reproducibility Readiness Score and itemized Missing Artifacts Manifest.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pypdf
    _PYPDF_AVAILABLE = True
except ImportError:
    _PYPDF_AVAILABLE = False


CHECKLIST_CRITERIA = {
    "Hyperparameters": {
        "weight": 20,
        "patterns": [
            (r"\blearning[- ]rate\b|\blr\b", "Learning Rate"),
            (r"\bbatch[- ]size\b", "Batch Size"),
            (r"\boptimizer\b|\badamw?\b|\bsgd\b", "Optimizer"),
            (r"\bepochs?\b|\btraining steps\b", "Epochs / Training Steps"),
            (r"\bweight[- ]decay\b|\bl2 regularization\b", "Weight Decay"),
        ],
    },
    "Random Seeds & Statistical Rigor": {
        "weight": 20,
        "patterns": [
            (r"\brandom[- ]seed\b|\bseed\s*=\s*\d+\b|\btorch\.manual_seed\b", "Specified Random Seed"),
            (r"\bstandard deviation\b|\bvariance\b|\bstd dev\b|\b±\b", "Variance / Standard Deviation"),
            (r"\bmultiple (?:runs|trials|seeds)\b|\b\d+\s*runs\b", "Multiple Trial Runs"),
            (r"\bp[- ]value\b|\bstatistical significance\b|\bconfidence interval\b", "Statistical Significance / CI"),
        ],
    },
    "Compute Environment & Hardware": {
        "weight": 15,
        "patterns": [
            (r"\b(?:nvidia|a100|h100|v100|rtx\s*\d{4}|tpu|gpu)\b", "Hardware / GPU Specification"),
            (r"\b(?:vram|gpu hours|training time|days to train)\b", "Compute Time / Memory Footprint"),
            (r"\bcuda\b|\bcudnn\b|\bdriver\b", "CUDA / Acceleration Framework"),
        ],
    },
    "Software Dependencies & Packaging": {
        "weight": 15,
        "patterns": [
            (r"\brequirements\.txt\b|\benvironment\.ya?ml\b|\bpoetry\.lock\b|\bpyproject\.toml\b", "Dependency File"),
            (r"\bpython\s*3\.\d+\b", "Python Version Pin"),
            (r"\bdocker(?:file)?\b|\bcontainer\b", "Containerization / Docker"),
        ],
    },
    "Code & Dataset Availability": {
        "weight": 20,
        "patterns": [
            (r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+", "Open Source Code Repository"),
            (r"https?://(?:www\.)?(?:huggingface\.co|zenodo\.org|kaggle\.com|osf\.io)/", "Public Dataset / Model Checkpoints"),
            (r"\b(?:train(?:ing)?/val(?:idation)?/test|data split|80/10/10|70/15/15)\b", "Dataset Split Ratios"),
        ],
    },
    "Evaluation & Baseline Benchmarking": {
        "weight": 10,
        "patterns": [
            (r"\bbaseline(?:s)?\b|\bcompared to\b|\bstate[- ]of[- ]the[- ]art\b", "Baseline Comparisons"),
            (r"\baccuracy\b|\bf1[- ]score\b|\bbleu\b|\brouge\b|\bperplexity\b|\bmse\b|\bmauve\b", "Standardized Metrics"),
        ],
    },
}


def _read_target(path_or_text: str) -> Tuple[str, str]:
    """Returns (content_text, target_label)."""
    p = Path(path_or_text).expanduser().resolve()
    if p.exists():
        if p.is_dir():
            # Code repository directory
            chunks = []
            for item in p.rglob("*"):
                if item.is_file() and item.name in ("README.md", "README", "requirements.txt", "environment.yml", "setup.py", "pyproject.toml", "Dockerfile"):
                    try:
                        chunks.append(f"--- File: {item.name} ---\n" + item.read_text(encoding="utf-8", errors="replace")[:3000])
                    except Exception:
                        pass
                elif item.is_file() and item.suffix in (".py", ".sh", ".yaml") and len(chunks) < 15:
                    try:
                        chunks.append(f"--- File: {item.relative_to(p)} ---\n" + item.read_text(encoding="utf-8", errors="replace")[:2000])
                    except Exception:
                        pass
            return "\n\n".join(chunks), f"Repository: {p.name}"
        elif p.suffix.lower() == ".pdf":
            if not _PYPDF_AVAILABLE:
                raise RuntimeError("pypdf is required to read PDF papers.")
            reader = pypdf.PdfReader(str(p))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages), f"Paper: {p.name}"
        else:
            return p.read_text(encoding="utf-8", errors="replace"), f"Document: {p.name}"
    return path_or_text, "Submitted Content"


def _audit_reproducibility(text: str) -> Dict[str, Any]:
    total_score = 0.0
    max_score = 0.0
    category_reports = {}
    missing_manifest = []

    for cat, data in CHECKLIST_CRITERIA.items():
        cat_weight = data["weight"]
        max_score += cat_weight
        matched = []
        missing = []

        for pattern, label in data["patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                matched.append(label)
            else:
                missing.append(label)
                missing_manifest.append(f"[{cat}] {label}")

        cat_score = (len(matched) / len(data["patterns"])) * cat_weight
        total_score += cat_score

        category_reports[cat] = {
            "score": round(cat_score, 1),
            "max": cat_weight,
            "matched": matched,
            "missing": missing,
        }

    pct = round((total_score / max_score) * 100) if max_score > 0 else 0
    grade = "A" if pct >= 90 else ("B" if pct >= 75 else ("C" if pct >= 60 else ("D" if pct >= 40 else "F")))

    return {
        "score_pct": pct,
        "grade": grade,
        "categories": category_reports,
        "missing_manifest": missing_manifest,
    }


def _synthesize_reproducibility_gemini(text: str, audit: Dict[str, Any], label: str) -> Optional[str]:
    from memory.config_manager import get_api_key
    api_key = get_api_key("gemini")
    if not api_key:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        prompt = (
            "You are ARC Reproducibility Agent, an expert peer reviewer and ML audit scientist.\n"
            f"Audit the scientific reproducibility of: {label}.\n\n"
            f"QUANTITATIVE AUDIT RESULTS:\n- Reproducibility Readiness Index: {audit['score_pct']}%\n"
            f"- Grade: {audit['grade']}\n- Missing Artifacts: {json.dumps(audit['missing_manifest'], indent=2)}\n\n"
            f"Paper / Artifact Text Excerpt:\n{text[:6000]}\n\n"
            "Produce an authoritative reproducibility critique in Markdown:\n"
            "### 1. Executive Summary & Reproducibility Readiness Index (0-100%)\n"
            "### 2. Dimension Audit Breakdown (Hyperparameters, Seeds/Variance, Compute, Dependencies, Code/Data)\n"
            "### 3. Missing Artifacts Manifest (Bulleted list of every missing parameter, checkpoint, or script)\n"
            "### 4. Independent Replication Protocol (Step-by-step instructions to reproduce experimental findings)"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"[ReproducibilityAgent] Gemini synthesis note: {e}")
    return None


def reproducibility_agent(parameters: dict, player=None, **_context) -> str:
    """Audit scientific research papers, ML models, and code repositories for empirical reproducibility."""
    raw_path = parameters.get("path") or parameters.get("file_path") or parameters.get("repo")
    raw_text = parameters.get("text")

    target = raw_path or raw_text
    if not target:
        return "Please provide 'path' (to a paper PDF/TXT or repository folder) or 'text' of the study."

    try:
        content, label = _read_target(target)
    except Exception as e:
        return f"Error reading target paper or repository: {e}"

    if not content.strip():
        return "Target content is empty or unreadable."

    audit = _audit_reproducibility(content)
    gemini_report = _synthesize_reproducibility_gemini(content, audit, label)

    if gemini_report:
        report = f"# ARC Reproducibility Readiness Audit: {label}\n\n{gemini_report}"
    else:
        # Structured local report
        lines = [
            f"# ARC Reproducibility Readiness Audit: {label}",
            f"**Reproducibility Readiness Index:** {audit['score_pct']}% | **Grade:** {audit['grade']}",
            "",
            "## 1. Reproducibility Checklist Dimensions",
        ]
        for cat, data in audit["categories"].items():
            lines.append(f"### {cat} ({data['score']}/{data['max']} pts)")
            if data["matched"]:
                lines.append(f"✓ Disclosed: {', '.join(data['matched'])}")
            if data["missing"]:
                lines.append(f"⚠️ Missing: {', '.join(data['missing'])}")
            lines.append("")

        lines.append("## 2. Missing Artifacts Manifest")
        if audit["missing_manifest"]:
            for m in audit["missing_manifest"]:
                lines.append(f"- [ ] {m}")
        else:
            lines.append("✅ All required empirical reproducibility artifacts are accounted for.")

        lines.extend([
            "",
            "## 3. Replication Protocol Recommendations",
            "1. Pin exact software versions into a deterministic `requirements.txt` or Docker image.",
            "2. Publish random seeds and report mean ± standard deviation across at least 3-5 independent runs.",
            "3. Provide direct public links to pre-trained model weights, evaluation scripts, and dataset splits.",
        ])
        report = "\n".join(lines)

    # Display on HUD if available
    try:
        if player and hasattr(player, "ui") and hasattr(player.ui, "show_content"):
            player.ui.show_content(f"Repro: {label[:20]}", report[:3800])
    except Exception:
        pass

    return report


TOOL = {
    "name": "reproducibility_agent",
    "description": (
        "Audit research papers, ML model cards, and code repositories for scientific reproducibility. "
        "Evaluates hyperparameters, random seeds, hardware specs, dependencies, code/data availability, "
        "and metrics to compute a 0-100% Reproducibility Score and an itemized Missing Artifacts Manifest."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "Path to paper (PDF, TXT, MD) or repository folder to audit.",
            },
            "text": {
                "type": "STRING",
                "description": "Direct text of the study or model card if no file is provided.",
            },
        },
    },
    "handler": reproducibility_agent,
}
