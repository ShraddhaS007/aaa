import os
import subprocess
import sys
import json


def run_cmd(cmd: list):
    try:
        print(f"$ {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}: {' '.join(cmd)}")
        return e.returncode


def main():
    input_dir = os.environ.get("INPUT_DIR", "/app/input")
    output_dir = os.environ.get("OUTPUT_DIR", "/app/output")
    os.makedirs(output_dir, exist_ok=True)

    # 1) Extract outlines per-PDF using Component 1A
    ret1 = run_cmd([sys.executable, "component-1a/1A.py", input_dir, "-o", output_dir])
    if ret1 != 0:
        print("Warning: Outline extraction encountered errors.")

    # 2) Run Component 1B analysis to produce output.json
    ret2 = run_cmd([sys.executable, "component-1b/1B.py", input_dir, output_dir])
    if ret2 != 0:
        print("Warning: Document analysis encountered errors.")

    # Done
    # Optional: create a simple HTML view for the final analysis
    try:
        out_json = os.path.join(output_dir, 'output.json')
        if os.path.exists(out_json):
            with open(out_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
            html_path = os.path.join(output_dir, 'output.html')
            html = [
                '<!doctype html>',
                '<html lang="en">',
                '<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">',
                '<title>Document Intelligence Report</title>',
                '<style>body{font-family:Arial,Helvetica,sans-serif;margin:24px;max-width:920px} h1{font-size:24px} h2{font-size:20px;margin-top:24px} .card{border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0} .muted{color:#666} code{background:#f6f8fa;padding:2px 4px;border-radius:4px}</style>',
                '</head>',
                '<body>'
            ]
            meta = data.get('metadata', {})
            html.append(f"<h1>Final Analysis</h1>")
            html.append('<div class="card">')
            html.append(f"<div><strong>Persona:</strong> {meta.get('persona','')}</div>")
            html.append(f"<div><strong>Task:</strong> {meta.get('job_to_be_done','')}</div>")
            html.append(f"<div class=\"muted\"><strong>Timestamp:</strong> {meta.get('processing_timestamp','')}</div>")
            html.append('</div>')

            html.append('<h2>Top Sections</h2>')
            for sec in data.get('extracted_sections', []):
                html.append('<div class="card">')
                html.append(f"<div><strong>Document:</strong> {sec.get('document','')}</div>")
                html.append(f"<div><strong>Section:</strong> {sec.get('section_title','')}</div>")
                html.append(f"<div><strong>Importance Rank:</strong> {sec.get('importance_rank','')}</div>")
                html.append(f"<div><strong>Page:</strong> {sec.get('page_number','')}</div>")
                html.append('</div>')

            html.append('<h2>Refined Subsections</h2>')
            for sub in data.get('subsection_analysis', []):
                html.append('<div class="card">')
                html.append(f"<div><strong>Document:</strong> {sub.get('document','')}</div>")
                html.append(f"<div><strong>Page:</strong> {sub.get('page_number','')}</div>")
                refined = (sub.get('refined_text') or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                html.append(f"<div style=\"margin-top:8px\">{refined}</div>")
                html.append('</div>')

            html.append('<hr><div class="muted">Open <code>output.json</code> for raw data.</div>')
            html.append('</body></html>')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(html))
            print(f"HTML report written to {html_path}")
    except Exception as e:
        print(f"Failed to create HTML report: {e}")

    print("Processing complete. Check /app/output for results.")


if __name__ == "__main__":
    main()

