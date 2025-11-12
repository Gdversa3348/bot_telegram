from PIL import Image
import re
from dateutil import parser as dateparser
import datetime
from typing import List, Tuple


# Detecta disponibilidade de engines de OCR
def detect_engine() -> str:
    """Retorna a engine de OCR disponível na ordem de preferência: paddle, easyocr, pytesseract, none."""
    try:
        import paddleocr  # type: ignore
        return 'paddle'
    except Exception:
        pass
    try:
        import easyocr  # type: ignore
        return 'easyocr'
    except Exception:
        pass
    try:
        import pytesseract  # type: ignore
        return 'pytesseract'
    except Exception:
        pass
    return 'none'


def ocr_image(image_path: str) -> str:
    """Executa OCR na imagem e retorna o texto extraído.
    Tenta (em ordem): PaddleOCR, EasyOCR, pytesseract.
    """
    # Tenta PaddleOCR
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True, lang='pt')
        res = ocr.ocr(image_path, cls=True)
        lines = []
        # res: list -> each detected line: [box, (text, confidence)]
        for block in res:
            # block pode ser uma lista de linhas
            for line in block:
                # cada line[-1][0] é o texto
                try:
                    lines.append(line[-1][0])
                except Exception:
                    # em alguns retornos a estrutura pode variar
                    try:
                        lines.append(line[1][0])
                    except Exception:
                        continue
        return "\n".join(lines)
    except Exception:
        pass

    # Tenta EasyOCR
    try:
        import easyocr
        reader = easyocr.Reader(['pt'], gpu=False)
        res = reader.readtext(image_path, detail=1, paragraph=True)
        # res: list of (bbox, text, confidence)
        texts = [r[1] for r in res]
        return "\n".join(texts)
    except Exception:
        pass

    # Fallback pytesseract
    try:
        import pytesseract
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang='por')
        return text
    except Exception as e:
        raise RuntimeError('Nenhum mecanismo de OCR disponível. Erro: ' + str(e))


def extract_amounts_dates(text: str) -> Tuple[List[float], List[datetime.date], List[str]]:
    """Extrai valores monetários e possíveis datas do texto.
    Retorna (valores, datas, linhas)
    """
    if not text:
        return [], [], []

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Regex para valores: captura formatos comuns com separador de milhares e decimais
    amount_re = re.compile(r'(?:R\$\s*)?([+-]?\d{1,3}(?:[\.\s]\d{3})*(?:[\,\.]\d{2})|[+-]?\d+[\,\.]\d{2})')
    values = []
    values_by_line = []
    for line in lines:
        for m in amount_re.finditer(line):
            s = m.group(1)
            v = s.replace(' ', '').replace('.', '').replace(',', '.')
            try:
                values.append(float(v))
                values_by_line.append((line, float(v)))
            except Exception:
                continue

    # Regex para datas como DD/MM/AAAA, DD/MM/AA
    date_candidates = re.findall(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text)
    dates = []
    for d in date_candidates:
        try:
            dt = dateparser.parse(d, dayfirst=True).date()
            dates.append(dt)
        except Exception:
            pass

    # Tenta detectar datas por parsing azaroso nas linhas (fuzzy)
    for line in lines:
        try:
            dt = dateparser.parse(line, dayfirst=True, fuzzy=True)
            if isinstance(dt, datetime.datetime):
                dates.append(dt.date())
        except Exception:
            pass

    # Remove duplicatas mantendo ordem
    seen = set()
    unique_dates = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            unique_dates.append(d)

    return values, unique_dates, lines


def choose_total_value(text: str, values_by_line: List[Tuple[str, float]] | None = None) -> float | None:
    """Heurística para escolher o valor total do comprovante.
    1) Procura por palavras-chave próximas ao valor
    2) Se não achar, retorna o maior valor positivo
    """
    if not text:
        return None

    if values_by_line is None:
        # Re-extract naive
        vals, _, _ = extract_amounts_dates(text)
        if not vals:
            return None
        return max(vals)

    keywords = ['total', 'valor a pagar', 'valor a pagar:', 'valor', 'a pagar', 'total a pagar', 'total:']
    for line, val in values_by_line:
        low = line.lower()
        if any(k in low for k in keywords):
            return val

    # Senão retorna maior valor
    vals = [v for _, v in values_by_line]
    if vals:
        return max(vals)
    return None


def parse_receipt(image_path: str) -> dict:
    """Executa OCR + heurísticas e retorna dict com chaves:
    - text, total (float|None), date (date|None), description (str|None), values (list[float])
    """
    text = ocr_image(image_path)
    values, dates, lines = extract_amounts_dates(text)

    # reconstrói values_by_line para escolher total com contexto
    amount_re = re.compile(r'(?:R\$\s*)?([+-]?\d{1,3}(?:[\.\s]\d{3})*(?:[\,\.]\d{2})|[+-]?\d+[\,\.]\d{2})')
    values_by_line = []
    for line in lines:
        for m in amount_re.finditer(line):
            s = m.group(1)
            v = s.replace(' ', '').replace('.', '').replace(',', '.')
            try:
                values_by_line.append((line, float(v)))
            except Exception:
                pass

    total = choose_total_value('\n'.join(lines), values_by_line)
    date = dates[0] if dates else None

    # heurística para descrição: pega primeira linha longa sem valor
    candidate_desc = [l for l in lines if not amount_re.search(l)]
    desc = candidate_desc[0][:200] if candidate_desc else None

    return {
        'text': text,
        'total': total,
        'date': date,
        'description': desc,
        'values': [v for _, v in values_by_line]
    }


def is_payment_receipt(parsed: dict) -> dict:
    """Classifica se o texto extraído parece um recibo/comprovante de pagamento.

    Usa heurísticas simples baseadas em palavras-chave, presença de valores e datas.
    Retorna um dict: {'is_payment': bool, 'score': float(0..1), 'reasons': [str]}.
    """
    text = (parsed.get('text') or '').lower()
    values = parsed.get('values') or []
    date = parsed.get('date')

    if not text:
        return {'is_payment': False, 'score': 0.0, 'reasons': ['empty_text']}

    reasons = []
    score = 0.0

    # Lista de palavras fortes indicando comprovante/recibo/transferência
    strong_keywords = [
        'comprovante', 'recibo', 'transfer', 'transferência', 'transferencia', 'pagamento', 'boleto',
        'saldo', 'agência', 'agencia', 'conta', 'operação', 'operacao', 'autoriz', 'favorecido',
        'cpf', 'cnpj', 'código barra', 'linha digitável'
    ]

    # Palavras que indicam total/valor
    value_keywords = ['total', 'valor a pagar', 'valor', 'total a pagar', 'valor pago', 'liquida']

    # Pontuação por palavras fortes
    matches = 0
    for k in strong_keywords:
        if k in text:
            matches += 1
            reasons.append(f'kw:{k}')

    score += min(matches, 6) * 1.5  # cada match soma até 1.5, cap em 9

    # Pontuação por ocorrência de palavras de valor
    vmatches = 0
    for k in value_keywords:
        if k in text:
            vmatches += 1
            reasons.append(f'valkw:{k}')
    score += min(vmatches, 3) * 2.0  # palavras de valor têm mais peso

    # Presença de valores detectados
    if values:
        reasons.append(f'values_count:{len(values)}')
        score += min(len(values), 4) * 1.0

    # Presença de data aumenta confiança
    if date:
        reasons.append('has_date')
        score += 1.5

    # Normalizar a pontuação para 0..1 (max estimado ~15)
    max_score = 15.0
    norm = max(0.0, min(1.0, score / max_score))

    is_payment = norm >= 0.35
    # marcar forte confidence threshold
    strong = norm >= 0.7

    return {
        'is_payment': is_payment,
        'score': norm,
        'strong': strong,
        'reasons': reasons
    }
