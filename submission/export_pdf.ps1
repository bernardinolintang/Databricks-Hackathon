# Export FlatFair_Round1_Deck.pptx to PDF with PowerPoint (Windows).
#   python build_deck.py --team "Your team" ; powershell -File export_pdf.ps1
$deck = Join-Path $PSScriptRoot "FlatFair_Round1_Deck.pptx"
$pdf = Join-Path $PSScriptRoot "FlatFair_Round1_Deck.pdf"
$ppt = New-Object -ComObject PowerPoint.Application
try {
    $pres = $ppt.Presentations.Open($deck, $true, $false, $false)
    $pres.SaveAs($pdf, 32)   # 32 = ppSaveAsPDF
    $pres.Close()
    Write-Host "Wrote $pdf"
} finally {
    $ppt.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
