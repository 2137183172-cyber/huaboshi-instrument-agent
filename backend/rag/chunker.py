from typing import List, Dict

def split_text(text: str, chunk_size: int = 500, overlap: int = 80) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def build_chunks(product_name: str, doc_type: str, pages: List[Dict]) -> List[Dict]:
    rows = []
    idx = 1
    for page in pages:
        page_no = page.get("page")
        text = " ".join(page.get("lines", []))
        for chunk in split_text(text):
            rows.append({
                "chunk_id": f"{product_name}_{page_no}_{idx}",
                "product_name": product_name,
                "doc_type": doc_type,
                "page": page_no,
                "text": chunk
            })
            idx += 1
    return rows