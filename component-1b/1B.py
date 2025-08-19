import fitz # PyMuPDF
import json
import re
from collections import Counter, defaultdict
import argparse
import os
import math
from datetime import datetime

# Offline-friendly stop words (small static set)
_STOP_WORDS = {
    'the','and','a','an','of','to','in','for','on','with','is','are','it','this','that','as','by','from','or','be','at','we','you','your','our','their','was','were','but','not','can','will','should','could','may','might','into','over','under','about'
}


# =====================================================================================
# COMPONENT 1: PDF Outline Extractor (No changes needed, it's a solid base)
# =====================================================================================
class PDFOutlineExtractor:
    """
    Extracts a hierarchical outline using an advanced, multi-pass structural
    analysis pipeline for high-precision heading detection.
    """
    def __init__(self, pdf_path: str):
        try:
            if len(pdf_path) > 260 and re.match(r'^[a-zA-Z]:\\', pdf_path):
                 pdf_path = "\\\\?\\" + pdf_path
            self.doc = fitz.open(pdf_path)
        except Exception as e:
            raise FileNotFoundError(f"Error opening or reading PDF file: {e}")

    def _is_bold_by_name(self, font_name: str) -> bool:
        return any(x in font_name.lower() for x in ['bold', 'black', 'heavy', 'condb', 'cbi'])

    def _get_text_blocks(self):
        """Pass 1: Reconstruct the document into logical text blocks."""
        blocks = []
        for page in self.doc:
            for block in page.get_text("dict")["blocks"]:
                if block['type'] == 0: # Text block
                    block_text = ""
                    span_styles = []
                    for line in block["lines"]:
                        for span in line["spans"]:
                            block_text += span["text"] + " "
                            span_styles.append((round(span['size']), self._is_bold_by_name(span['font'])))
                    
                    if not block_text.strip() or not re.search('[a-zA-Z]', block_text): continue
                    if not span_styles: continue
                    dominant_style = Counter(span_styles).most_common(1)[0][0]
                    
                    blocks.append({
                        'text': block_text.strip(),
                        'style': dominant_style,
                        'bbox': block['bbox'],
                        'page_num': page.number + 1,
                        'num_lines': len(block['lines']),
                        'num_words': len(block_text.split())
                    })
        return blocks

    def _find_body_style(self, blocks):
        """Pass 2: Identify the primary body text style based on total word count."""
        style_word_counts = defaultdict(int)
        for block in blocks:
            if block['num_lines'] > 2 or block['num_words'] > 20:
                style_word_counts[block['style']] += block['num_words']
        
        if not style_word_counts:
            style_freq = Counter(b['style'] for b in blocks)
            if not style_freq: return None
            return style_freq.most_common(1)[0][0]

        return max(style_word_counts, key=style_word_counts.get)

    def get_outline(self) -> dict:
        """Orchestrates the multi-pass pipeline to extract the outline."""
        title = self._extract_title()
        
        toc = self.doc.get_toc()
        if toc:
            outline = [{"level": f"H{level}", "text": text.strip(), "page_num": page, "bbox": None} for level, text, page in toc if 1 <= level <= 4]
            outline = [h for h in outline if re.search('[a-zA-Z]', h['text'])]
            if outline:
                return {"title": title, "outline": outline}

        all_blocks = self._get_text_blocks()
        if not all_blocks:
            return {"title": title, "outline": []}
            
        body_style = self._find_body_style(all_blocks)
        if not body_style:
            return {"title": title, "outline": []}

        heading_blocks = []
        for block in all_blocks:
            if block['num_words'] > 30 or block['num_lines'] > 3:
                continue
            
            is_candidate = block['style'][0] > body_style[0] or \
                           (block['style'][0] == body_style[0] and block['style'][1] and not body_style[1])
            if not is_candidate:
                continue

            text = block['text'].strip()
            if re.search(r'\.{4,}', text) or text.endswith(('.', ',', ';', ':')):
                continue
            if re.match(r'^\s*([•*-]|[a-zA-Z\d]+\))\s+', text):
                continue

            heading_blocks.append(block)

        if not heading_blocks:
            return {"title": title, "outline": []}

        heading_styles = sorted(list(set(b['style'] for b in heading_blocks)), key=lambda x: (x[0], x[1]), reverse=True)
        
        style_to_level = {}
        level_map = ['H1', 'H2', 'H3', 'H4']
        
        # Group by size first
        size_groups = defaultdict(list)
        for style in heading_styles:
            size_groups[style[0]].append(style)
        
        sorted_sizes = sorted(size_groups.keys(), reverse=True)

        for i, size in enumerate(sorted_sizes):
            if i >= len(level_map): break
            level = level_map[i]
            # Within a size group, bold styles are ranked higher
            for style in sorted(size_groups[size], key=lambda x: x[1], reverse=True):
                 style_to_level[style] = level

        final_outline = []
        list_item_pattern = re.compile(r'^\s*(\d+(\.\d+)*)\s+')
        for block in heading_blocks:
            if block['style'] in style_to_level:
                level = style_to_level[block['style']]
                text = ' '.join(block['text'].split())
                
                match = list_item_pattern.match(text)
                if match:
                    dot_count = match.group(1).count('.')
                    level = f"H{dot_count + 1}"

                if level == 'H1' and block['page_num'] == 1 and text == title:
                    continue

                final_outline.append({'text': text, 'level': level, 'page_num': block['page_num'], 'bbox': block['bbox']})
        
        return {"title": title, "outline": sorted(final_outline, key=lambda x: (x['page_num'], x['bbox'][1] if x['bbox'] else 0))}

    def _extract_title(self) -> str:
        if self.doc.metadata and (title := self.doc.metadata.get("title", "").strip()):
            if len(title) > 4 and not re.search(r'\.(pdf|docx?|pptx?|xlsx?|cdr)$', title, re.I) and "Microsoft Word" not in title:
                return title
        if not self.doc or self.doc.page_count == 0: return ""
        first_page = self.doc[0]
        top_rect = fitz.Rect(0, 0, first_page.rect.width, first_page.rect.height * 0.4)
        blocks = first_page.get_text("dict", clip=top_rect).get('blocks', [])
        font_sizes = defaultdict(list)
        for block in blocks:
            if block['type'] == 0:
                for line in block['lines']:
                    line_text = " ".join(s['text'].strip() for s in line['spans'] if s['text'].strip()).strip()
                    if line_text and re.search('[a-zA-Z]', line_text) and len(line_text.split()) < 20:
                        if line['spans']:
                            avg_size = round(sum(s['size'] for s in line['spans']) / len(line['spans']))
                            font_sizes[avg_size].append(line_text)
        if font_sizes:
            max_size = max(font_sizes.keys())
            return " ".join(font_sizes[max_size])
        return ""

# =====================================================================================
# COMPONENT 2: Document Sectionizer (No changes needed)
# =====================================================================================
class DocumentSectionizer:
    def __init__(self, pdf_path: str):
        self.doc = fitz.open(pdf_path)
        # Use a more robust way to handle potential empty outlines
        outline_data = PDFOutlineExtractor(pdf_path).get_outline()
        self.outline = outline_data.get('outline', [])

    def get_sections(self) -> list:
        sections = []
        for i, heading in enumerate(self.outline):
            if 'bbox' not in heading or not heading['bbox']: continue
            
            start_page = heading['page_num'] - 1
            start_y = heading['bbox'][3] 

            next_heading = None
            for j in range(i + 1, len(self.outline)):
                if 'bbox' in self.outline[j] and self.outline[j]['bbox']:
                    next_heading = self.outline[j]
                    break
            
            if next_heading:
                end_page = next_heading['page_num'] - 1
                end_y = next_heading['bbox'][1]
            else:
                end_page = len(self.doc) - 1
                end_y = self.doc[end_page].rect.height
            
            content = ""
            for page_num in range(start_page, end_page + 1):
                page = self.doc[page_num]
                clip_y_start = start_y if page_num == start_page else 0
                clip_y_end = end_y if page_num == end_page else page.rect.height
                if clip_y_start < clip_y_end:
                    clip_rect = fitz.Rect(0, clip_y_start, page.rect.width, clip_y_end)
                    content += page.get_text(clip=clip_rect)
            
            cleaned_content = re.sub(r'(\w)-\n(\w)', r'\1\2', content)
            cleaned_content = re.sub(r'\s*\n\s*', ' ', cleaned_content)
            cleaned_content = ' '.join(cleaned_content.split())

            sections.append({
                'section_title': heading['text'], 
                'page_number': heading['page_num'], 
                'content': f"{heading['text']}. {cleaned_content}"
            })
        return sections

# --- NEW: COMPONENT 3: Advanced Query Processor ---
class QueryProcessor:
    def get_keywords(self, text: str, max_keywords=10) -> list:
        """Extracts keywords by removing stop words and taking most frequent terms."""
        words = re.findall(r'\b\w+\b', text.lower())
        filtered_words = [word for word in words if word not in _STOP_WORDS and len(word) > 2]
        return [word for word, freq in Counter(filtered_words).most_common(max_keywords)]

# --- NEW: COMPONENT 4: Hybrid Ranker (Replaces SemanticRanker) ---
class HybridRanker:
    def __init__(self, alpha: float = 1.0):
        # alpha retained for future extension; lexical-only for offline operation
        self.alpha = alpha

    def _idf(self, terms: list, documents: list) -> dict:
        num_docs = len(documents)
        df = Counter()
        for doc in documents:
            tokens = set(re.findall(r'\b\w+\b', doc.lower()))
            for t in terms:
                if t in tokens:
                    df[t] += 1
        idf = {}
        for t in terms:
            idf[t] = math.log((num_docs + 1) / (df[t] + 1)) + 1.0
        return idf

    def rank_sections(self, query: str, query_keywords: list, all_sections: list):
        if not all_sections:
            return [], None
        corpus = [sec['content'] for sec in all_sections]
        idf = self._idf(query_keywords, corpus)
        for section in all_sections:
            words = re.findall(r'\b\w+\b', section['content'].lower())
            tf = Counter(words)
            score = 0.0
            for q in query_keywords:
                score += tf.get(q, 0) * idf.get(q, 0.0)
            # Normalize by document length to avoid long-section bias
            denom = math.log(len(words) + 1) + 1
            section['relevance_score'] = score / denom
        return sorted(all_sections, key=lambda x: x['relevance_score'], reverse=True), None

# --- NEW: COMPONENT 5: Sub-Section Analyzer ---
class SubSectionAnalyzer:
    def __init__(self):
        pass

    def _split_sentences(self, text: str):
        # Simple rule-based sentence splitter
        parts = re.split(r'(?<=[\.!?])\s+', text.strip())
        return [p.strip() for p in parts if p.strip()]

    def get_refined_text(self, section_content: str, query_keywords, num_sentences=5) -> str:
        sentences = self._split_sentences(section_content)
        if not sentences:
            return ""
        scores = []
        for idx, sent in enumerate(sentences):
            words = re.findall(r'\b\w+\b', sent.lower())
            score = sum(1 for w in words if w in query_keywords)
            if idx == 0:
                score += 0.2  # slight boost to the first sentence
            scores.append((score, idx, sent))
        scores.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        top = sorted(scores[:num_sentences], key=lambda x: x[1])
        return " ".join(s[2] for s in top)

# =====================================================================================
# MAIN EXECUTION BLOCK (MODIFIED)
# =====================================================================================
def main():
    parser = argparse.ArgumentParser(description="Persona-Driven Document Intelligence System.")
    # --- MODIFIED: The script now processes all subdirectories in the input folder ---
    parser.add_argument("input_dir", type=str, help="Path to the main input directory containing collection subdirectories.")
    parser.add_argument("output_dir", type=str, help="Path to the main output directory.")
    args = parser.parse_args()

    # Offline-friendly components
    ranker = HybridRanker(alpha=1.0)
    sub_section_analyzer = SubSectionAnalyzer()
    query_processor = QueryProcessor()
    
    processed_any = False

    # If there are subdirectories, treat each as a collection; otherwise treat input_dir itself
    entries = [d for d in os.listdir(args.input_dir) if os.path.isdir(os.path.join(args.input_dir, d))]
    collection_roots = entries if entries else ["."]

    for collection_name in collection_roots:
        collection_dir = os.path.join(args.input_dir, collection_name) if collection_name != "." else args.input_dir

        print(f"--- Processing Collection: {collection_name} ---")
        input_json_path = os.path.join(collection_dir, 'challenge1b_input.json')
        
        try:
            with open(input_json_path, 'r', encoding='utf-8') as f: config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error reading or parsing {input_json_path}: {e}")
            continue
        
        persona = config.get('persona', {}).get('role', '')
        job_to_be_done = config.get('job_to_be_done', {}).get('task', '')
        query_text = f"User Persona: {persona}. Task: {job_to_be_done}"
        query_keywords = query_processor.get_keywords(query_text)

        documents = config.get('documents', [])
        # Look for PDFs next to the JSON first; if the 'PDFs' subfolder exists, prefer it
        candidate_pdf_dir = os.path.join(collection_dir, 'PDFs')
        pdf_dir = candidate_pdf_dir if os.path.isdir(candidate_pdf_dir) else collection_dir
        
        all_sections = []
        for doc in documents:
            pdf_path = os.path.join(pdf_dir, doc['filename'])
            doc_name = doc['filename']
            print(f"  - Sectionizing: {doc_name}")
            if not os.path.exists(pdf_path):
                print(f"    - Warning: File not found, skipping: {pdf_path}")
                continue
            try:
                sectionizer = DocumentSectionizer(pdf_path)
                sections = sectionizer.get_sections()
                for section in sections:
                    section['document'] = doc_name
                all_sections.extend(sections)
            except Exception as e:
                print(f"    - Could not process {doc_name}. Error: {e}")

        if not all_sections:
            print("  - No sections extracted. Skipping ranking.")
            continue

        print(f"  - Ranking {len(all_sections)} sections...")
        ranked_sections, query_embedding = ranker.rank_sections(query_text, query_keywords, all_sections)
        
        output_data = {
            "metadata": {
                "input_documents": [doc['filename'] for doc in documents],
                "persona": persona,
                "job_to_be_done": job_to_be_done,
                "processing_timestamp": datetime.utcnow().isoformat()
            },
            "extracted_sections": [],
            "subsection_analysis": []
        }
        
        for i, section in enumerate(ranked_sections[:10]):
            output_data["extracted_sections"].append({
                "document": section['document'],
                "section_title": section['section_title'],
                "importance_rank": i + 1,
                "page_number": section['page_number']
            })
            
        print("  - Generating refined text for top sections...")
        for section in ranked_sections[:5]:
            refined_text = sub_section_analyzer.get_refined_text(section['content'], query_keywords)
            output_data["subsection_analysis"].append({
                "document": section['document'],
                "refined_text": refined_text,
                "page_number": section['page_number']
            })
        
        # --- MODIFIED: Create a subdirectory in the output for each collection ---
        collection_output_dir = os.path.join(args.output_dir, collection_name) if collection_name != "." else args.output_dir
        os.makedirs(collection_output_dir, exist_ok=True)
        output_json_path = os.path.join(collection_output_dir, 'challenge1b_output.json') if collection_name != "." else os.path.join(collection_output_dir, 'output.json')

        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)
        
        print(f"--- Analysis for {collection_name} complete. Output saved to {output_json_path} ---\n")
        processed_any = True

    if not processed_any:
        print("No valid collections found to process.")

if __name__ == "__main__":
    main()