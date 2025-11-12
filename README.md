# Bot Telegram  Instruções de instalação e uso

Este repositório contém um bot Telegram que registra transações (entrada de valores via texto ou imagem) em um banco SQLite e fornece comandos de resumo/extrato.

O bot usa OCR para extrair valores de imagens (PaddleOCR preferível, EasyOCR e pytesseract como fallback) e uma heurística/"IA leve" para detectar comprovantes/recibos.

## Arquivos importantes
- `bot_telegram/bot.py`  handlers do bot, fluxo de OCR, confirmações interativas e integração com o DB.
- `bot_telegram/ocr.py`  código que executa OCR (Paddle/EasyOCR/pytesseract) e heurísticas de extração/classificação.
- `bot_telegram/db.py`  operações SQLite (transações, logs).
- `requirements.txt`  dependências do projeto (instalar no venv recomendado).
- `run.ps1`  script PowerShell para ativar venv (procura `C:\venv` ou `./venv`) e rodar o bot como módulo.

---

## Sumário rápido (Windows / PowerShell)
1. Criar e ativar um virtualenv em um caminho curto (recomendado: `C:\venv`).
2. Definir `TELEGRAM_TOKEN` (variável de ambiente) ou passar ao `run.ps1` com `-Token`.
3. Instalar dependências com `pip install -r requirements.txt` dentro do venv.
4. (Windows) Se encontrar erros de "long path" ao instalar pacotes grandes (p.ex. paddleocr), veja a seção "Windows long-path / instalação pesada".
5. Rodar o bot com `./run.ps1` ou `python -m bot_telegram.bot`.

---

## Passo a passo completo (PowerShell)

### 1) Abra PowerShell e vá para a raiz do projeto:

```powershell
cd 'C:\Users\<SeuUser>\OneDrive\Documentos\1. PROGRAMAÇÃO\Bot_Telegram'
```

### 2) Criar um virtualenv em um caminho curto (recomendado para Windows):

```powershell
# cria venv em C:\venv (recomendado para evitar problemas de caminhos longos)
python -m venv C:\venv

# ativa o venv (usa Activate.ps1)
& 'C:\venv\Scripts\Activate.ps1'
```

Se preferir um venv local ao projeto, use `python -m venv .\venv` e ative `& '.\venv\Scripts\Activate.ps1'`.

### 3) (Opcional) Ajustar TEMP para pip (ajuda em instalações grandes):

```powershell
New-Item -Path 'C:\temp' -ItemType Directory -ErrorAction SilentlyContinue
$env:TEMP = 'C:\temp'
$env:TMP  = 'C:\temp'
```

### 4) Instalar dependências (dentro do venv):

```powershell
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-cache-dir -r .\requirements.txt
```

**Observações sobre `requirements.txt`**
- O arquivo inclui pacotes grandes como `paddlepaddle` e `paddleocr`. Eles são pesados e podem demorar/ter requisitos específicos (CPU vs GPU). Se não precisar do Paddle (por exemplo, aceitar EasyOCR), você pode instalar apenas as dependências leves:

```powershell
python -m pip install python-telegram-bot pillow python-dateutil pytesseract easyocr
```

### 5) Certifique-se de que o Tesseract OCR esteja instalado se quiser usar `pytesseract` (fallback):

- Baixe e instale: https://github.com/UB-Mannheim/tesseract/wiki
- Verifique o executável: `where.exe tesseract` ou `tesseract --version` no PowerShell.

### 6) Defina o token do Telegram (recomendado) ou passe no `run.ps1`:

```powershell
# Para a sessão atual do PowerShell (temp):
$env:TELEGRAM_TOKEN = 'SEU_TOKEN_AQUI'

# Ou use o run.ps1 e passe como parâmetro:
.\run.ps1 -Token 'SEU_TOKEN_AQUI'
```

### 7) Executar o bot:

```powershell
# opção 1 (script que ativa venv e roda como módulo):
powershell -ExecutionPolicy Bypass -NoProfile -File .\run.ps1 -Token 'SEU_TOKEN_AQUI'

# opção 2 (direto com python do venv):
& 'C:\venv\Scripts\python.exe' -m bot_telegram.bot
```

---

## Problemas comuns e soluções rápidas

- **Erro:** "execution of scripts is disabled" ao rodar `run.ps1`  rode com ExecutionPolicy Bypass temporariamente:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -File .\run.ps1 -Token 'SEU_TOKEN'
```

- **Erro durante pip install com OSError relacionado a caminhos longos**  crie venv em `C:\venv` e utilize `--no-cache-dir` e ajuste TEMP para `C:\temp` (veja passos acima). Alternativamente, habilite LongPaths no Windows (exige admin).

- **Erro:** "Conflict: terminated by other getUpdates request"  significa que outra instância ou webhook está consumindo os updates do mesmo token. Solução:

```powershell
$token = $env:TELEGRAM_TOKEN # ou defina manualmente
Invoke-RestMethod "https://api.telegram.org/bot$token/getWebhookInfo" | ConvertTo-Json -Depth 5
Invoke-RestMethod "https://api.telegram.org/bot$token/deleteWebhook"
# Depois reinicie apenas uma instância do bot localmente
```

---

## Detalhes sobre OCR e "IA" de detecção de comprovantes

- O projeto prioriza PaddleOCR (quando disponível) por ser mais preciso. EasyOCR e pytesseract são fallbacks.
- O arquivo `bot_telegram/ocr.py` contém heurísticas para:
  - extrair valores e datas,
  - escolher qual valor parece ser o "total",
  - classificar (heuristicamente) se o texto faz parte de um comprovante/recibo (função `is_payment_receipt`).
- Fluxo do bot ao receber uma imagem:
  1. Roda OCR (Paddle > EasyOCR > pytesseract).
  2. Extrai valores e datas.
  3. Usa `is_payment_receipt` para decidir entre:
     - adicionar automaticamente (alta confiança),
     - pedir confirmação ao usuário (confiança média),
     - adicionar automaticamente mas sinalizar baixa confiança (se nenhuma indicação de comprovante).

---

## Logs e depuração

- Ao iniciar o bot você verá logs como:
  - `[INFO] OCR engine detected: paddle`  qual engine foi detectada/selecionada.
  - Mensagens sobre deleteWebhook e uso do TELEGRAM_TOKEN.
- Se algo der errado, cole o traceback aqui (ou veja os logs) e eu te ajudo a diagnosticar.

---

## Extras / recomendações

- Para desenvolvimento eu recomendo criar o venv em `C:\venv` e instalar `paddleocr` lá apenas se precisar de mais precisão. Isso evita o problema de caminhos longos no Windows.
- Se quiser que eu adicione um `start_dev.ps1` que automaticamente remove o webhook, mata instâncias Python extras e inicia o bot, eu posso criar no repositório.

## Contribuindo

- Abra issues com exemplos de imagens (privadas), sugestões de palavras-chave para o classificador, ou melhorias na heurística.

## Licença

- Este repositório não inclui uma licença por padrão. Se for publicar no GitHub, recomendo adicionar uma (MIT ou similar) se quiser permitir contribuições.

----

Se quiser, eu atualizo também o README principal na raiz do repositório com link para estas instruções ou crio o `start_dev.ps1`. Diga qual ação prefere.
