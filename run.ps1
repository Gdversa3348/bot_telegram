Param(
    [string]$Token
)

# Script simples para ativar virtualenv (procura em C:\venv ou ./venv) e rodar o bot como módulo
Write-Host "== Iniciando run.ps1: ativando venv e executando bot como módulo =="

$psRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Preferência: venv em C:\venv
$venvActivate = 'C:\venv\Scripts\Activate.ps1'
if (-not (Test-Path $venvActivate)) {
    # fallback para venv local na raiz do projeto
    $localVenv = Join-Path $psRoot 'venv\Scripts\Activate.ps1'
    if (Test-Path $localVenv) {
        $venvActivate = $localVenv
    } else {
        $venvActivate = $null
    }
}

if ($venvActivate) {
    Write-Host "Ativando virtualenv: $venvActivate"
    try {
        & $venvActivate
    } catch {
        Write-Warning "Falha ao ativar venv: $_.Exception.Message"
    }
} else {
    Write-Warning "Nenhum virtualenv encontrado em C:\venv ou ./venv. Continuando sem ativar um venv."
}

if ($Token) {
    Write-Host "Usando token passado por parâmetro (será exportado como TELEGRAM_TOKEN para a sessão)."
    $env:TELEGRAM_TOKEN = $Token
}

Write-Host "Executando: python -m bot_telegram.bot"
python -m bot_telegram.bot
