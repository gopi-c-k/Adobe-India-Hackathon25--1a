import fitz  # PyMuPDF
import json
from collections import defaultdict
import re
from typing import List, Dict, Any
import os

# ---------- Configuration ----------
MIN_HEADING_WORDS = 2
MAX_HEADING_WORDS = 15
MIN_PARAGRAPH_WORDS = 8
MAX_HEADING_DENSITY = 0.6
HEADING_SCORE_THRESHOLD = 5
TITLE_CANDIDATE_PAGES = 1  # Only look at first page for title

# Blocklist patterns
BLOCKLIST_REGEX = [
    r"^\d+$", r"^[ivxlcdm]+$", r"^[a-z]$", r"^Table of Contents$",
    r"^Appendix$", r"^Index$", r"^References$", r"^Bibliography$",
    r"^\s*$", r"^[^a-zA-Z0-9]+$", r"^(Chapter|Section|Fig|Figure|Table)\b",
    r"\b\d{1,2}(st|nd|rd|th)?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\b", r"^\d{1,2}/\d{1,2}/\d{2,4}$",
    r"^\d{4}-\d{2}-\d{2}$"
]
compiled_blocklist = [re.compile(p, re.IGNORECASE) for p in BLOCKLIST_REGEX]

# ---------- Utility Functions ----------
def is_blocked(text: str) -> bool:
    text = text.strip()
    return not text or any(p.match(text) for p in compiled_blocklist)

def calculate_text_density(text: str, bbox: List[float]) -> float:
    text_width = bbox[2] - bbox[0]
    return len(text) / text_width if text_width > 0 else 0

# ---------- Text Classification ----------
def is_paragraph(text: str) -> bool:
    text = text.strip()
    if not text or len(text.split()) < MIN_PARAGRAPH_WORDS:
        return False

    paragraph_indicators = [
        r'^[A-Z][a-z].*[.!?]$', r'.*\b[a-z]{3,}\b.*',
        r'.*,\s[a-z].*', r'.*\b(and|the|of|in|to)\b', r'.{50,}'
    ]
    return sum(1 for p in paragraph_indicators if re.search(p, text)) >= 3

def is_heading_like(text: str) -> bool:
    text = text.strip()
    if not text or len(text.split()) > MAX_HEADING_WORDS:
        return False

    heading_indicators = [
        (r'^([A-Z][a-z]*)(\s+[A-Z][a-z]*)*$', 2), (r'^[A-Z][a-z][^.!?]*$', 1),
        (r'^[A-Z][^?.]*\?$', 2), (r'^\d+\.\s+[A-Z]', 2),
        (r'^[A-Z]\w*(:\s+[A-Z][a-z][^.!?]*)?$', 1)
    ]

    score = sum(points for p, points in heading_indicators if re.match(p, text))
    if re.search(r'[.!]$', text) and not text.endswith('?'): score -= 2
    if text and text[0].islower() and len(text.split()) > 3: score -= 1

    return score >= 2

# ---------- Text Extraction ----------
def extract_text_with_style(pdf_path: str) -> List[Dict[str, Any]]:
    doc = fitz.open(pdf_path)
    elements = []

    for page_num, page in enumerate(doc):
        page_width = page.rect.width
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    line_text = "".join(span["text"] for span in line["spans"]).strip()
                    if is_blocked(line_text):
                        continue

                    font_size = max(span["size"] for span in line["spans"])
                    flags = line["spans"][0]["flags"]
                    bbox = line["bbox"]

                    elements.append({
                        "page": page_num + 1,
                        "text": line_text,
                        "font_size": font_size,
                        "bold": bool(flags & 2),
                        "italic": bool(flags & 4),
                        "caps": line_text.isupper(),
                        "words": len(line_text.split()),
                        "centered": abs(bbox[0] - (page_width - bbox[2])) < 20,
                        "density": calculate_text_density(line_text, bbox),
                        "bbox": bbox,
                        "is_paragraph": is_paragraph(line_text),
                        "heading_like": is_heading_like(line_text)
                    })
    return elements

# ---------- Title Detection ----------
def find_title(elements: List[Dict[str, Any]]) -> str:
    first_page_elements = [e for e in elements if e["page"] == 1 and not is_blocked(e["text"])]
    if not first_page_elements:
        return ""

    max_font = max(e["font_size"] for e in first_page_elements)
    title_candidates = [e for e in first_page_elements if abs(e["font_size"] - max_font) < 0.5]

    title_candidates.sort(key=lambda x: x["bbox"][1])
    title_text = " ".join(c["text"] for c in title_candidates[:3]).strip()
    return title_text

# ---------- Heading Processing ----------
def process_headings(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not elements:
        return []

    non_para_sizes = [e["font_size"] for e in elements if not e["is_paragraph"]]
    if not non_para_sizes:
        return []

    avg_size = sum(non_para_sizes) / len(non_para_sizes)
    size_range = max(non_para_sizes) - min(non_para_sizes)

    candidates = []
    for e in elements:
        if e["is_paragraph"]:
            continue

        size_ratio = (e["font_size"] - avg_size) / (size_range + 1e-6)
        score = (3 if size_ratio > 0.5 else
                 2 if size_ratio > 0.2 else
                 1 if size_ratio > 0 else 0)

        score += 2 if e["bold"] else 0
        score += 1 if e["caps"] and e["words"] <= 8 else 0
        score += 1 if e["centered"] else 0
        score += 1 if e["words"] <= 10 else (0.5 if e["words"] <= 15 else 0)
        score += 1 if e["density"] < MAX_HEADING_DENSITY else 0
        score += 2 if e["heading_like"] else 0

        if score >= HEADING_SCORE_THRESHOLD:
            candidates.append({**e, "score": score})

    return candidates

def assign_heading_levels(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    clusters = defaultdict(list)
    for c in candidates:
        style_key = (
            round(c["font_size"] * 2) / 2,
            c["bold"],
            c["italic"],
            c["caps"],
            c["centered"]
        )
        clusters[style_key].append(c)

    sorted_clusters = sorted(clusters.items(),
                             key=lambda x: (-x[0][0], -sum(c["score"] for c in x[1]) / len(x[1])))

    headings = []
    for level, (_, items) in enumerate(sorted_clusters, start=1):
        for item in items:
            headings.append({
                "level": f"H{min(level, 6)}",
                "text": item["text"],
                "page": item["page"],
                "font_size": item["font_size"],
                "position": item["bbox"]
            })

    headings.sort(key=lambda x: (x["page"], x["position"][1]))
    return headings

# ---------- Main Function ----------
def extract_document_structure(pdf_path: str) -> Dict[str, Any]:
    elements = extract_text_with_style(pdf_path)
    title = find_title(elements)
    candidates = process_headings(elements)
    headings = assign_heading_levels(candidates)

    return {
        "title": title,
        "outline": [{"level": h["level"], "text": h["text"], "page": h["page"]}
                    for h in headings]
    }

def save_to_json(data: Dict[str, Any], output_path: str) -> None:
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ---------- Batch Execution ----------
INPUT_DIR = "/app/input"
OUTPUT_DIR = "/app/output"

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for file in os.listdir(INPUT_DIR):
        if file.lower().endswith(".pdf"):
            pdf_path = os.path.join(INPUT_DIR, file)
            output_path = os.path.join(OUTPUT_DIR, file.rsplit(".", 1)[0] + ".json")

            try:
                result = extract_document_structure(pdf_path)
                save_to_json(result, output_path)
                print(f"✅ Processed: {file}")
            except Exception as e:
                print(f"❌ Failed to process {file}: {e}")

    print("🎯 Finished processing all PDFs")
