from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from backend.local_catalog import get_local_device_detail
from backend.product_publication import public_payload
router = APIRouter()

@router.get("/api/products/brochure")
def product_brochure(name: str = ""):
    detail = get_local_device_detail((name or "").strip())
    if not detail:
        raise HTTPException(status_code=404, detail="未找到该产品资料页")
    detail = public_payload(detail)

    def esc(value):
        import html
        return html.escape(str(value or ""))

    sections = [
        ("产品简介", detail.get("overview")),
        ("产品优势", detail.get("advantages")),
        ("应用场景", detail.get("applications")),
        ("技术参数", "\n".join(detail.get("key_specs", []))),
        ("配置需求（非标配承诺）", detail.get("product_configuration")),
        ("适用样本", "；".join(detail.get("sample_types", []))),
    ]
    body = "\n".join(
        f"<section><h2>{esc(title)}</h2><p>{esc(value or '-').replace(chr(10), '<br>')}</p></section>"
        for title, value in sections
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(detail.get('name'))} - 产品资料页</title>
  <style>
    body {{ margin: 0; padding: 32px; color: #172033; font-family: "Microsoft YaHei", sans-serif; background: #f6f8fc; }}
    main {{ max-width: 920px; margin: 0 auto; background: #fff; border-radius: 18px; padding: 30px; box-shadow: 0 18px 48px rgba(31,48,84,.12); }}
    h1 {{ margin: 0 0 10px; font-size: 30px; }}
    .meta {{ color: #64748b; line-height: 1.8; margin-bottom: 24px; }}
    section {{ border-top: 1px solid #e5eaf3; padding-top: 18px; margin-top: 18px; }}
    h2 {{ font-size: 18px; margin: 0 0 10px; color: #0c7ff2; }}
    p {{ line-height: 1.8; white-space: normal; }}
  </style>
</head>
<body>
<main>
  <h1>{esc(detail.get('name'))}</h1>
  <div class="meta">
    型号：{esc(detail.get('product_code') or '-')}<br>
    品牌/厂家：{esc(detail.get('brand_vendor') or '-')}<br>
    供货单位：{esc(detail.get('supplier_name') or '-')}<br>
    来源品牌：{esc(detail.get('brand_name') or '-')}
  </div>
  {body or '<p>该产品暂未收录完整资料。</p>'}
</main>
</body>
</html>"""
    return HTMLResponse(html)
