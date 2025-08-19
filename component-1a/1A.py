import fitz
import json
import re
from collections import Counter, defaultdict
import argparse

class PDFOutlineExtractor:
    """
    Extracts a hierarchical outline (Title, H1, H2, H3) from a PDF document.

    This is a highly optimized and robust version that uses a multi-stage
    heuristic pipeline to achieve high accuracy across diverse document types,
    including articles, reports, and forms.
    """

    def __init__(self, pdf_path: str):
        """
        Initializes the extractor with the path to the PDF file.
        """
        try:
            if len(pdf_path) > 260 and re.match(r'^[a-zA-Z]:\\', pdf_path):
                 pdf_path = "\\\\?\\" + pdf_path
            self.doc = fitz.open(pdf_path)
        except Exception as e:
            raise FileNotFoundError(f"Error opening or reading PDF file: {e}")

        self.page_margin_top = 0.08
        self.page_margin_bottom = 0.92
        self.min_heading_length = 3
        self.max_heading_length = 300

    def _is_bold_by_name(self, font_name: str) -> bool:
        """Checks if a font name suggests it is bold for better accuracy."""
        return any(x in font_name.lower() for x in ['bold', 'black', 'heavy', 'condb', 'cbi'])

    def _extract_title(self) -> str:
        """
        Extracts the document title using a robust hybrid approach.
        """
        if self.doc.metadata and (title := self.doc.metadata.get("title", "").strip()):
            if len(title) > 4 and not re.search(r'\.(pdf|docx?|pptx?|xlsx?|cdr)$', title, re.I) and "Microsoft Word" not in title:
                return title

        if not self.doc or self.doc.page_count == 0:
            return ""

        first_page = self.doc[0]
        top_rect = fitz.Rect(0, 0, first_page.rect.width, first_page.rect.height * 0.5)
        
        blocks = first_page.get_text("dict", clip=top_rect).get('blocks', [])
        
        font_sizes = defaultdict(list)
        for block in blocks:
            if block['type'] == 0:
                for line in block['lines']:
                    line_text = " ".join(span['text'].strip() for span in line['spans'] if span['text'].strip()).strip()
                    if line_text and re.search('[a-zA-Z]', line_text):
                        if line['spans']:
                             avg_size = round(sum(s['size'] for s in line['spans']) / len(line['spans']))
                             font_sizes[avg_size].append(line_text)
        
        if font_sizes:
            max_size = max(font_sizes.keys())
            # Join all text fragments with the largest font size.
            return " ".join(font_sizes[max_size])

        return ""

    def _reconstruct_lines(self):
        """Reconstructs all lines from the document into a structured list, merging spans."""
        all_lines = []
        for page_num, page in enumerate(self.doc):
            content_rect = fitz.Rect(0, page.rect.height * self.page_margin_top, page.rect.width, page.rect.height * self.page_margin_bottom)
            blocks = page.get_text("dict", clip=content_rect).get("blocks", [])
            
            lines_on_page = defaultdict(list)
            for block in blocks:
                if block['type'] == 0:
                    for line in block['lines']:
                        # Group spans by a quantized vertical position to merge lines accurately
                        y0 = round(line['bbox'][1] / 5.0) * 5.0
                        lines_on_page[y0].extend(line['spans'])
            
            for y0 in sorted(lines_on_page.keys()):
                spans = lines_on_page[y0]
                if not spans: continue
                
                spans.sort(key=lambda s: s['bbox'][0])
                
                line_text = " ".join(span['text'].strip() for span in spans if span['text'].strip()).strip()
                if not line_text: continue
                
                first_span = spans[0]
                style = (round(first_span['size']), self._is_bold_by_name(first_span['font']))
                
                all_lines.append({
                    'text': line_text,
                    'style': style,
                    'page_num': page_num + 1,
                })
        return all_lines

    def _classify_styles(self, lines: list) -> dict:
        """
        Classifies font styles into Body, H1, H2, etc., using a sophisticated
        statistical and contextual analysis.
        """
        if not lines:
            return {}

        style_profiles = defaultdict(lambda: {'count': 0, 'total_words': 0})
        for line in lines:
            style = line['style']
            style_profiles[style]['count'] += 1
            style_profiles[style]['total_words'] += len(line['text'].split())

        if not style_profiles:
            return {}

        for style, profile in style_profiles.items():
            profile['avg_words'] = profile['total_words'] / profile['count']

        non_heading_styles = {s for s, p in style_profiles.items() if p['avg_words'] > 20}
        try:
            body_style_candidate = Counter({s: p['count'] for s, p in style_profiles.items() if s not in non_heading_styles}).most_common(1)[0][0]
        except IndexError:
            return {}

        heading_candidates = []
        for style, profile in style_profiles.items():
            is_candidate = style[0] > body_style_candidate[0] or \
                           (style[0] == body_style_candidate[0] and style[1] and not body_style_candidate[1])
            if not is_candidate:
                continue

            if profile['avg_words'] > 15:
                continue
            
            heading_candidates.append(style)
        
        if not heading_candidates:
            return {}
        
        largest_heading_size = max(s[0] for s in heading_candidates)
        if largest_heading_size < body_style_candidate[0] * 1.15:
            return {}

        size_groups = defaultdict(list)
        for size, bold in set(heading_candidates):
            size_groups[size].append((size, bold))

        sorted_sizes = sorted(size_groups.keys(), reverse=True)
        
        style_to_level = {}
        level_map = ['H1', 'H2', 'H3', 'H4']
        for i, size in enumerate(sorted_sizes):
            if i < len(level_map):
                level = level_map[i]
                sorted_styles_in_group = sorted(size_groups[size], key=lambda s: s[1], reverse=True)
                for style in sorted_styles_in_group:
                    style_to_level[style] = level
        
        return style_to_level

    def extract_outline(self) -> dict:
        """
        Orchestrates the entire outline extraction process using a robust pipeline.
        """
        title = self._extract_title()
        
        toc = self.doc.get_toc()
        if toc:
            outline = [{"level": f"H{level}", "text": text.strip(), "page": page} for level, text, page in toc if 1 <= level <= 4]
            outline = [h for h in outline if re.search('[a-zA-Z]', h['text'])]
            if outline:
                 return {"title": title, "outline": outline}

        all_lines = self._reconstruct_lines()
        style_to_level = self._classify_styles(all_lines)
        
        if not style_to_level:
            return {"title": title, "outline": []}
            
        outline = []
        url_pattern = re.compile(r'https?://\S+')
        toc_pattern = re.compile(r'\.{4,}')
        list_item_pattern = re.compile(r'^\s*(\d+(\.\d+)*)\s+')

        for line in all_lines:
            line_text = line['text']
            
            if not (self.min_heading_length <= len(line_text) <= self.max_heading_length) or url_pattern.match(line_text):
                continue
            
            if toc_pattern.search(line_text):
                continue
            
            if line['style'] in style_to_level:
                level = style_to_level[line['style']]
                clean_text = ' '.join(line_text.split())

                if level == 'H1' and line['page_num'] == 1 and clean_text == title:
                    continue
                
                match = list_item_pattern.match(clean_text)
                if match:
                    num_str = match.group(1).strip()
                    dot_count = num_str.count('.')
                    # Refine level based on numbering
                    if dot_count == 0: level = 'H1'
                    elif dot_count == 1: level = 'H2'
                    elif dot_count == 2: level = 'H3'
                    else: level = 'H4'

                if not any(o['text'] == clean_text and o['page'] == line['page_num'] for o in outline):
                    outline.append({
                        "level": level,
                        "text": clean_text,
                        "page": line['page_num']
                    })

        return {"title": title, "outline": outline}


def _process_single_pdf(pdf_path: str) -> dict:
    extractor = PDFOutlineExtractor(pdf_path)
    outline = extractor.extract_outline()
    try:
        doc = fitz.open(pdf_path)
        num_pages = doc.page_count
    finally:
        try:
            doc.close()
        except Exception:
            pass
    outline["source_pdf"] = pdf_path.split("/")[-1]
    outline["num_pages"] = num_pages
    return outline


def main():
    parser = argparse.ArgumentParser(description="Extract a structured outline from a PDF file or directory of PDFs.")
    parser.add_argument("input", type=str, help="Path to the input PDF file or a directory containing PDFs.")
    parser.add_argument("-o", "--output", type=str, help="Path to the output JSON file when input is a single PDF. If input is a directory, provide an output directory.")
    args = parser.parse_args()

    try:
        import os
        if os.path.isdir(args.input):
            if not args.output:
                raise ValueError("When input is a directory, --output must be provided and point to an output directory.")
            os.makedirs(args.output, exist_ok=True)
            processed = 0
            for name in sorted(os.listdir(args.input)):
                if not name.lower().endswith(".pdf"):
                    continue
                in_path = os.path.join(args.input, name)
                try:
                    result = _process_single_pdf(in_path)
                    out_path = os.path.join(args.output, f"{os.path.splitext(name)[0]}.json")
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                    print(f"Extracted outline -> {out_path}")
                    processed += 1
                except Exception as e:
                    print(f"Failed to process {in_path}: {e}")
            if processed == 0:
                print("No PDFs found to process.")
        else:
            result = _process_single_pdf(args.input)
            json_output = json.dumps(result, indent=2, ensure_ascii=False)
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(json_output)
                print(f"Successfully extracted outline to {args.output}")
            else:
                print(json_output)

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()