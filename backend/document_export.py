from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
import base64
import re
import struct
import secrets
import sqlite3
import time
import html
from urllib.parse import quote
from contextlib import contextmanager
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, HTMLResponse
from pydantic import BaseModel, Field

router = APIRouter()
EXPORT_DB = '/tmp/huaboshi-document-downloads.sqlite3'
EXPORT_TTL = 86400

@contextmanager
def export_db():
    db = sqlite3.connect(EXPORT_DB, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS exports (token TEXT PRIMARY KEY, created REAL, title TEXT, document BLOB, preview TEXT)')
    try:
        with db:
            yield db
    finally:
        db.close()

def get_export(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(404, 'File not found')
    with export_db() as db:
        row = db.execute('SELECT title, document, preview FROM exports WHERE token=? AND created>?', (token, time.time()-EXPORT_TTL)).fetchone()
    if not row:
        raise HTTPException(410, '下载链接已过期，请返回华博士重新生成文档')
    return row

class DocumentRequest(BaseModel):
    title: str = Field(default='华博士方案', max_length=200)
    maps: list[str] = Field(min_length=1, max_length=60)
    headers: list[str] = Field(min_length=5, max_length=5)
    rows: list[list[str]] = Field(default_factory=list, max_length=1000)

def paragraph(text, heading=False):
    text = escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(text)))
    props = '<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="160"/></w:pPr>' if heading else '<w:pPr><w:spacing w:after="80"/></w:pPr>'
    style = '<w:rPr><w:b/><w:color w:val="126576"/><w:sz w:val="26"/></w:rPr>' if heading else ''
    return '<w:p>' + props + ''.join('<w:r>' + style + '<w:t xml:space="preserve">' + line + '</w:t><w:br/></w:r>' for line in text.split('\n')) + '</w:p>'

def build_document(payload):
    body = [paragraph(payload.title, True), paragraph('方案思维导图', True)]
    media = []
    rels = ['<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>']
    for index, encoded in enumerate(payload.maps):
        try:
            if len(encoded) > 8000000:
                raise ValueError()
            png = base64.b64decode(encoded, validate=True)
            if png[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError()
            width, height = struct.unpack('>II', png[16:24])
            if not (0 < width <= 4000 and 0 < height <= 4000):
                raise ValueError()
        except (ValueError, struct.error):
            raise HTTPException(422, 'Invalid mindmap image')
        cx = 6000000
        cy = int(cx * height / width)
        if cy > 7600000:
            cx, cy = int(cx * 7600000 / cy), 7600000
        rid = f'image{index}'
        media.append((f'word/media/{rid}.png', png))
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{rid}.png"/>')
        body.append(f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{index+1}" name="方案思维导图"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="{index+1}" name="{rid}.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    body.append(paragraph('方案设备明细', True))
    widths = [1750, 1300, 1550, 3540, 1500]
    if payload.rows:
        table = ['<w:tbl><w:tblPr><w:tblW w:w="9640" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders>' + ''.join(f'<w:{edge} w:val="single" w:sz="4" w:color="C6DDE2"/>' for edge in ['top','left','bottom','right','insideH','insideV']) + '</w:tblBorders><w:tblCellMar><w:top w:w="100" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>' + ''.join(f'<w:gridCol w:w="{width}"/>' for width in widths) + '</w:tblGrid>']
        for index, row in enumerate([payload.headers, *payload.rows]):
            table.append('<w:tr>' + ('<w:trPr><w:tblHeader/></w:trPr>' if index == 0 else ''))
            for column in range(5):
                fill = 'E6F3F6' if index == 0 else ('F4F8FA' if index % 2 == 0 else 'FFFFFF')
                table.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[column]}" w:type="dxa"/><w:shd w:fill="{fill}"/></w:tcPr>' + paragraph(row[column] if column < len(row) else '-', index == 0) + '</w:tc>')
            table.append('</w:tr>')
        body.append(''.join(table) + '</w:tbl>')
    else:
        body.append(paragraph('该方案暂无设备明细。'))
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
    document = '<?xml version="1.0" encoding="UTF-8"?><w:document ' + ns + '><w:body>' + ''.join(body) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1000" w:right="1133" w:bottom="1000" w:left="1133"/></w:sectPr></w:body></w:document>'
    styles = '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="Microsoft YaHei"/><w:sz w:val="20"/><w:color w:val="33434A"/></w:rPr></w:rPrDefault></w:docDefaults></w:styles>'
    contents = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'
    root_rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    doc_rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(rels) + '</Relationships>'
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, content in [('word/document.xml',document), ('word/styles.xml',styles), ('[Content_Types].xml',contents), ('_rels/.rels',root_rels), ('word/_rels/document.xml.rels',doc_rels)]:
            archive.writestr(name, content.encode('utf-8'))
        for name, content in media:
            archive.writestr(name, content)
    return output.getvalue()

@router.post('/api/export/docx')
def export_document(payload: DocumentRequest):
    if sum(map(len, payload.maps)) > 24000000 or sum(len(str(row)) for row in payload.rows) > 250000:
        raise HTTPException(413, 'Document too large')
    title = re.sub(r'[\\/:*?"<>|\r\n]', '-', payload.title)[:80] or '华博士方案'
    return Response(build_document(payload), media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers={'Content-Disposition':f'attachment; filename="huaboshi-plan.docx"; filename*=UTF-8\'\'{quote(title+".docx")}', 'Cache-Control':'no-store'})

@router.post('/api/export/prepare')
def prepare_export(payload: DocumentRequest):
    if sum(map(len, payload.maps)) > 24000000 or sum(len(str(row)) for row in payload.rows) > 250000:
        raise HTTPException(413, 'Document too large')
    document = build_document(payload)
    token = secrets.token_urlsafe(32)
    title = re.sub(r'[\\/:*?"<>|\r\n]', '-', payload.title)[:80] or '华博士方案'
    images = ''.join('<img alt="方案思维导图" src="data:image/png;base64,' + encoded + '">' for encoded in payload.maps)
    table = '<table><thead><tr>' + ''.join('<th>'+html.escape(h)+'</th>' for h in payload.headers) + '</tr></thead><tbody>'
    for row in payload.rows:
        table += '<tr>' + ''.join('<td>'+html.escape(row[i] if i<len(row) else '—')+'</td>' for i in range(5)) + '</tr>'
    table += '</tbody></table>'
    preview = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>body{font:15px/1.6 system-ui,sans-serif;color:#233438;margin:0;padding:16px;max-width:960px;margin:auto}h1{font-size:21px}a{color:#075dba;font-weight:700}header{padding-bottom:16px;border-bottom:1px solid #ddd}img{display:block;width:100%;height:auto;margin:16px 0}table{border-collapse:collapse;min-width:680px;width:100%}th,td{border:1px solid #c6dde2;padding:8px;text-align:left;white-space:pre-wrap}th{background:#e6f3f6}.table{overflow:auto}p{color:#52636c}input{width:100%;box-sizing:border-box;padding:8px;font-size:14px}</style><header><h1>'+html.escape(title)+'</h1><a href="/api/export/file/'+token+'.docx">下载完整方案word文档</a><p>微信内若无法下载，请点击右上角“…”选择在浏览器打开，再点击下载。下载后可用 Word 或 WPS 打开。</p><p>链接有效期24小时。也可长按复制下方链接到系统浏览器：</p><input aria-label="方案链接" readonly value=""><p><a href="/">返回华博士</a></p></header><h2>方案思维导图</h2>'+images+'<h2>方案设备明细</h2><div class="table">'+table+'</div><script>document.querySelector("input").value=location.href;</script></html>'
    with export_db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM exports WHERE created<?', (time.time()-EXPORT_TTL,))
        used = db.execute('SELECT COALESCE(SUM(length(document)+length(preview)),0) FROM exports').fetchone()[0]
        if used + len(document) + len(preview.encode('utf-8')) > 100*1024*1024:
            raise HTTPException(503, '下载服务繁忙，请稍后重试')
        db.execute('INSERT INTO exports VALUES (?,?,?,?,?)', (token,time.time(),title,document,preview))
    return {'download_url':f'/api/export/file/{token}.docx', 'preview_url':f'/api/export/view/{token}', 'expires_in':EXPORT_TTL}

@router.get('/api/export/file/{token}.docx')
def download_export(token: str):
    title, document, _ = get_export(token)
    return Response(document, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers={'Content-Disposition':f'attachment; filename="huaboshi-plan.docx"; filename*=UTF-8\'\'{quote(title+".docx")}', 'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer'})

@router.get('/api/export/view/{token}', response_class=HTMLResponse)
def preview_export(token: str):
    _, _, preview = get_export(token)
    return HTMLResponse(preview, headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})
